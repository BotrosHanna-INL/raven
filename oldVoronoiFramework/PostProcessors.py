"""
Created on July 10, 2013

@author: alfoa
"""
from __future__ import division, print_function , unicode_literals, absolute_import
import warnings
warnings.simplefilter('default', DeprecationWarning)

#External Modules------------------------------------------------------------------------------------
import numpy as np
from scipy import spatial, interpolate, integrate
from scipy.spatial.qhull import QhullError
import os
from glob import glob
import copy
import math
from collections import OrderedDict
from scipy.spatial import ConvexHull,Voronoi, voronoi_plot_2d
from operator import mul
from collections import defaultdict
import itertools
import pyhull as ph
import pyhull.halfspace as phh
import sys
#External Modules End--------------------------------------------------------------------------------

#Internal Modules------------------------------------------------------------------------------------
import utils
import mathUtils
import DataObjects
from Assembler import Assembler
import SupervisedLearning
import MessageHandler
import GridEntities
import Files
from RAVENiterators import ravenArrayIterator
#Internal Modules End--------------------------------------------------------------------------------

"""
  ***************************************
  *  SPECIALIZED PostProcessor CLASSES  *
  ***************************************
"""

class BasePostProcessor(Assembler, MessageHandler.MessageUser):
  """"This is the base class for postprocessors"""
  def __init__(self, messageHandler):
    """
     Constructor
     @ In, messageHandler, message handler object
    """
    self.type = self.__class__.__name__  # pp type
    self.name = self.__class__.__name__  # pp name
    self.assemblerObjects = {}  # {MainClassName(e.g.Distributions):[class(e.g.Models),type(e.g.ROM),objectName]}
    self.requiredAssObject = (False, ([], []))  # tuple. self.first entry boolean flag. True if the XML parser must look for assembler objects;
                                                      # second entry tuple.self.first entry list of object can be retrieved, second entry multiplicity (-1,-2,-n means optional (max 1 object,2 object, no number limit))
    self.assemblerDict = {}  # {'class':[['subtype','name',instance]]}
    self.messageHandler = messageHandler

  def initialize(self, runInfo, inputs, initDict) :
    """
     Method to initialize the pp.
     @ In, runInfo, dict, dictionary of run info (e.g. working dir, etc)
     @ In, inputs, list, list of inputs
     @ In, initDict, dict, dictionary with initialization options
    """
    # if 'externalFunction' in initDict.keys(): self.externalFunction = initDict['externalFunction']
    self.inputs = inputs

  def inputToInternal(self, currentInput):
    """
     Method to convert an input object into the internal format that is
     understandable by this pp.
     @ In, currentInput, object, an object that needs to be converted
     @ Out, list, list of current inputs
    """
    return [(copy.deepcopy(currentInput))]

  def run(self, Input):
    """
     This method executes the postprocessor action.
     @ In,  Input, object, object contained the data to process. (inputToInternal output)
     @ Out, dictionary, Dictionary containing the evaluated data
    """
    pass

class LimitSurfaceIntegral(BasePostProcessor):
  """
  This post-processor is aimed to compute the n-dimensional integral of an inputted Limit Surface
  """
  def __init__(self, messageHandler):
    """
     Constructor
     @ In, messageHandler, message handler object
    """
    BasePostProcessor.__init__(self, messageHandler)
    self.variableDist = {}  # dictionary created upon the .xml input file reading. It stores the distributions for each variable.
    self.target = None  # target that defines the f(x1,x2,...,xn)
    self.tolerance = 0.0001  # integration tolerance
    self.integralType = 'montecarlo'  # integral type (which alg needs to be used). Either montecarlo or quadrature(quadrature not yet)
    self.seed = 20021986  # seed for montecarlo
    self.matrixDict = {}  # dictionary of arrays and target
    self.lowerUpperDict = {}
    self.functionS = None
    self.stat = returnInstance('BasicStatistics', self)  # instantiation of the 'BasicStatistics' processor, which is used to compute the pb given montecarlo evaluations
    self.stat.what = ['expectedValue']
    self.requiredAssObject = (False, (['Distribution'], ['n']))
    self.printTag = 'POSTPROCESSOR INTEGRAL'

  def _localWhatDoINeed(self):
    """
    This method is a local mirror of the general whatDoINeed method.
    It is implemented by this postprocessor that need to request special objects
    @ In , None, None
    @ Out, needDict, list of objects needed
    """
    needDict = {'Distributions':[]}
    for distName in self.variableDist.values():
      if distName != None: needDict['Distributions'].append((None, distName))
    return needDict

  def _localGenerateAssembler(self, initDict):
    """ see generateAssembler method in Assembler.py """
    for varName, distName in self.variableDist.items():
      if distName != None:
        if distName not in initDict['Distributions'].keys(): self.raiseAnError(IOError, 'distribution ' + distName + ' not found.')
        self.variableDist[varName] = initDict['Distributions'][distName]
        self.lowerUpperDict[varName]['lowerBound'] = self.variableDist[varName].lowerBound
        self.lowerUpperDict[varName]['upperBound'] = self.variableDist[varName].upperBound

  def _localReadMoreXML(self, xmlNode):
    """
    Function to read the portion of the xml input that belongs to this specialized class
    and initialize some stuff based on the inputs got
    @ In, xmlNode    : Xml element node
    @ Out, None
    """
    for child in xmlNode:
      varName = None
      if child.tag == 'variable':
        varName = child.attrib['name']
        self.lowerUpperDict[varName] = {}
        self.variableDist[varName] = None
        for childChild in child:
          if childChild.tag == 'distribution': self.variableDist[varName] = childChild.text
          elif childChild.tag == 'lowerBound':
            if self.variableDist[varName] != None: self.raiseAnError(NameError, 'you can not specify both distribution and lower/upper bounds nodes for variable ' + varName + ' !')
            self.lowerUpperDict[varName]['lowerBound'] = float(childChild.text)
          elif childChild.tag == 'upperBound':
            if self.variableDist[varName] != None: self.raiseAnError(NameError, 'you can not specify both distribution and lower/upper bounds nodes for variable ' + varName + ' !')
            self.lowerUpperDict[varName]['upperBound'] = float(childChild.text)
          else:
            self.raiseAnError(NameError, 'invalid labels after the variable call. Only "distribution", "lowerBound" abd "upperBound" is accepted. tag: ' + child.tag)
      elif child.tag == 'tolerance':
        try              : self.tolerance = float(child.text)
        except ValueError: self.raiseAnError(ValueError, "tolerance can not be converted into a float value!")
      elif child.tag == 'integralType':
        self.integralType = child.text.strip().lower()
        if self.integralType not in ['montecarlo']: self.raiseAnError(IOError, 'only one integral types are available: MonteCarlo!')
      elif child.tag == 'seed':
        try              : self.seed = int(child.text)
        except ValueError: self.raiseAnError(ValueError, 'seed can not be converted into a int value!')
        if self.integralType != 'montecarlo': self.raiseAWarning('integral type is ' + self.integralType + ' but a seed has been inputted!!!')
        else: np.random.seed(self.seed)
      elif child.tag == 'target':
        self.target = child.text
      else: self.raiseAnError(NameError, 'invalid or missing labels after the variables call. Only "variable" is accepted.tag: ' + child.tag)
      # if no distribution, we look for the integration domain in the input
      if varName != None:
        if self.variableDist[varName] == None:
          if 'lowerBound' not in self.lowerUpperDict[varName].keys() or 'upperBound' not in self.lowerUpperDict[varName].keys():
            self.raiseAnError(NameError, 'either a distribution name or lowerBound and upperBound need to be specified for variable ' + varName)
    if self.target == None: self.raiseAWarning('integral target has not been provided. The postprocessor is going to take the last output it finds in the provided limitsurface!!!')

  def initialize(self, runInfo, inputs, initDict):
    """
     Method to initialize the Limit Surface Integral post-processor. This method here
     is in charge of 'training' the nearest Neighbors ROM.
     @ In, runInfo, dict, dictionary of run info (e.g. working dir, etc)
     @ In, inputs, list, list of inputs
     @ In, initDict, dict, dictionary with initialization options
    """
    self.inputToInternal(inputs)
    if self.integralType in ['montecarlo']:
      self.stat.parameters['targets'] = [self.target]
      self.stat.initialize(runInfo, inputs, initDict)
    self.functionS = SupervisedLearning.returnInstance('SciKitLearn', self, **{'SKLtype':'neighbors|KNeighborsClassifier', 'Features':','.join(list(self.variableDist.keys())), 'Target':self.target})
    self.functionS.train(self.matrixDict)
    self.raiseADebug('DATA SET MATRIX:')
    self.raiseADebug(self.matrixDict)

  def inputToInternal(self, currentInput):
    """
     Method to convert an input object into the internal format that is
     understandable by this pp.
     @ In, currentInput, object, an object that needs to be converted
     @ Out, None, the resulting converted object is stored as an attribute of this class
    """
    for item in currentInput:
      if item.type == 'PointSet':
        self.matrixDict = {}
        if not set(item.getParaKeys('inputs')) == set(self.variableDist.keys()): self.raiseAnError(IOError, 'The variables inputted and the features in the input PointSet ' + item.name + 'do not match!!!')
        if self.target == None: self.target = item.getParaKeys('outputs')[-1]
        if self.target not in item.getParaKeys('outputs'): self.raiseAnError(IOError, 'The target ' + self.target + 'is not present among the outputs of the PointSet ' + item.name)
        # construct matrix
        for  varName in self.variableDist.keys(): self.matrixDict[varName] = item.getParam('input', varName)
        outputarr = item.getParam('output', self.target)
        if len(set(outputarr)) != 2: self.raiseAnError(IOError, 'The target ' + self.target + ' needs to be a classifier output (-1 +1 or 0 +1)!')
        outputarr[outputarr == -1] = 0.0
        self.matrixDict[self.target] = outputarr
      else: self.raiseAnError(IOError, 'Only PointSet is accepted as input!!!!')

  def run(self, Input):
    """
     This method executes the postprocessor action. In this case, it performs the computation of the LS integral
     @ In,  Input, object, object contained the data to process. (inputToInternal output)
     @ Out, float, integral outcome (probability of the event)
    """
    pb = None
    if self.integralType == 'montecarlo':
      tempDict = {}
      randomMatrix = np.random.rand(int(math.ceil(1.0 / self.tolerance**2)), len(self.variableDist.keys()))
      for index, varName in enumerate(self.variableDist.keys()):
        if self.variableDist[varName] == None: randomMatrix[:, index] = randomMatrix[:, index] * (self.lowerUpperDict[varName]['upperBound'] - self.lowerUpperDict[varName]['lowerBound']) + self.lowerUpperDict[varName]['lowerBound']
        else:
          for samples in range(randomMatrix.shape[0]): randomMatrix[samples, index] = self.variableDist[varName].ppf(randomMatrix[samples, index])
        tempDict[varName] = randomMatrix[:, index]
      pb = self.stat.run({'targets':{self.target:self.functionS.evaluate(tempDict)}})
    else: self.raiseAnError(NotImplemented, "quadrature not yet implemented")
    return pb['expectedValue'][self.target]

  def collectOutput(self, finishedjob, output):
    """
      Function to place all of the computed data into the output object
      @ In, finishedJob: A JobHandler object that is in charge of running this
                         post-processor
      @ In, output: The object where we want to place our computed results
      @ Out, None
    """
    if finishedjob.returnEvaluation() == -1: self.raiseAnError(RuntimeError, 'no available output to collect.')
    else:
      pb = finishedjob.returnEvaluation()[1]
      lms = finishedjob.returnEvaluation()[0][0]
      if output.type == 'PointSet':
        # we store back the limitsurface
        for key, value in lms.getParametersValues('input').items():
          for val in value: output.updateInputValue(key, val)
        for key, value in lms.getParametersValues('output').items():
          for val in value: output.updateOutputValue(key, val)
        for _ in range(len(lms)): output.updateOutputValue('EventProbability', pb)
      elif isinstance(output,Files.File):
        headers = lms.getParaKeys('inputs') + lms.getParaKeys('outputs')
        if 'EventProbability' not in headers: headers += ['EventProbability']
        stack = [None] * len(headers)
        output.close()
        outIndex = 0
        for key, value in lms.getParametersValues('input').items() : stack[headers.index(key)] = np.asarray(value).flatten()
        for key, value in lms.getParametersValues('output').items():
          stack[headers.index(key)] = np.asarray(value).flatten()
          outIndex = headers.index(key)
        stack[headers.index('EventProbability')] = np.array([pb] * len(stack[outIndex])).flatten()
        stacked = np.column_stack(stack)
        np.savetxt(output, stacked, delimiter = ',', header = ','.join(headers),comments='')
        #N.B. without comments='' you get a "# " at the top of the header row
      else: self.raiseAnError(Exception, self.type + ' accepts PointSet or File type only')
#
#
#
class SafestPoint(BasePostProcessor):
  """
  It searches for the probability-weighted safest point inside the space of the system controllable variables
  """
  def __init__(self, messageHandler):
    """
     Constructor
     @ In, messageHandler, message handler object
    """
    BasePostProcessor.__init__(self, messageHandler)
    self.controllableDist = {}  # dictionary created upon the .xml input file reading. It stores the distributions for each controllale variable.
    self.nonControllableDist = {}  # dictionary created upon the .xml input file reading. It stores the distributions for each non-controllale variable.
    self.controllableGrid = {}  # dictionary created upon the .xml input file reading. It stores the grid type ('value' or 'CDF'), the number of steps and the step length for each controllale variable.
    self.nonControllableGrid = {}  # dictionary created upon the .xml input file reading. It stores the grid type ('value' or 'CDF'), the number of steps and the step length for each non-controllale variable.
    self.gridInfo = {}  # dictionary contaning the grid type ('value' or 'CDF'), the grid construction type ('equal', set by default) and the list of sampled points for each variable.
    self.controllableOrd = []  # list contaning the controllable variables' names in the same order as they appear inside the controllable space (self.controllableSpace)
    self.nonControllableOrd = []  # list contaning the controllable variables' names in the same order as they appear inside the non-controllable space (self.nonControllableSpace)
    self.surfPointsMatrix = None  # 2D-matrix containing the coordinates of the points belonging to the failure boundary (coordinates are derived from both the controllable and non-controllable space)
    self.stat = returnInstance('BasicStatistics', self)  # instantiation of the 'BasicStatistics' processor, which is used to compute the expected value of the safest point through the coordinates and probability values collected in the 'run' function
    self.stat.what = ['expectedValue']
    self.requiredAssObject = (True, (['Distribution'], ['n']))
    self.printTag = 'POSTPROCESSOR SAFESTPOINT'

  def _localGenerateAssembler(self, initDict):
    """ see generateAssembler method in Assembler """
    for varName, distName in self.controllableDist.items():
      if distName not in initDict['Distributions'].keys():
        self.raiseAnError(IOError, 'distribution ' + distName + ' not found.')
      self.controllableDist[varName] = initDict['Distributions'][distName]
    for varName, distName in self.nonControllableDist.items():
      if distName not in initDict['Distributions'].keys():
        self.raiseAnError(IOError, 'distribution ' + distName + ' not found.')
      self.nonControllableDist[varName] = initDict['Distributions'][distName]

  def _localReadMoreXML(self, xmlNode):
    """
    Function to read the portion of the xml input that belongs to this specialized class
    and initialize some stuff based on the inputs got
    @ In, xmlNode    : Xml element node
    @ Out, None
    """
    for child in xmlNode:
      if child.tag == 'controllable':
        for childChild in child:
          if childChild.tag == 'variable':
            varName = childChild.attrib['name']
            for childChildChild in childChild:
              if childChildChild.tag == 'distribution':
                self.controllableDist[varName] = childChildChild.text
              elif childChildChild.tag == 'grid':
                if 'type' in childChildChild.attrib.keys():
                  if 'steps' in childChildChild.attrib.keys():
                    self.controllableGrid[varName] = (childChildChild.attrib['type'], int(childChildChild.attrib['steps']), float(childChildChild.text))
                  else:
                    self.raiseAnError(NameError, 'number of steps missing after the grid call.')
                else:
                  self.raiseAnError(NameError, 'grid type missing after the grid call.')
              else:
                self.raiseAnError(NameError, 'invalid labels after the variable call. Only "distribution" and "grid" are accepted.')
          else:
            self.raiseAnError(NameError, 'invalid or missing labels after the controllable variables call. Only "variable" is accepted.')
      elif child.tag == 'non-controllable':
        for childChild in child:
          if childChild.tag == 'variable':
            varName = childChild.attrib['name']
            for childChildChild in childChild:
              if childChildChild.tag == 'distribution':
                self.nonControllableDist[varName] = childChildChild.text
              elif childChildChild.tag == 'grid':
                if 'type' in childChildChild.attrib.keys():
                  if 'steps' in childChildChild.attrib.keys():
                    self.nonControllableGrid[varName] = (childChildChild.attrib['type'], int(childChildChild.attrib['steps']), float(childChildChild.text))
                  else:
                    self.raiseAnError(NameError, 'number of steps missing after the grid call.')
                else:
                  self.raiseAnError(NameError, 'grid type missing after the grid call.')
              else:
                self.raiseAnError(NameError, 'invalid labels after the variable call. Only "distribution" and "grid" are accepted.')
          else:
            self.raiseAnError(NameError, 'invalid or missing labels after the controllable variables call. Only "variable" is accepted.')
    self.raiseADebug('CONTROLLABLE DISTRIBUTIONS:')
    self.raiseADebug(self.controllableDist)
    self.raiseADebug('CONTROLLABLE GRID:')
    self.raiseADebug(self.controllableGrid)
    self.raiseADebug('NON-CONTROLLABLE DISTRIBUTIONS:')
    self.raiseADebug(self.nonControllableDist)
    self.raiseADebug('NON-CONTROLLABLE GRID:')
    self.raiseADebug(self.nonControllableGrid)

  def initialize(self, runInfo, inputs, initDict):
    """
     Method to initialize the Safest Point pp. This method is in charge
     of creating the Controllable and no-controllable grid.
     @ In, runInfo, dict, dictionary of run info (e.g. working dir, etc)
     @ In, inputs, list, list of inputs
     @ In, initDict, dict, dictionary with initialization options
    """
    self.__gridSetting__()
    self.__gridGeneration__()
    self.inputToInternal(inputs)
    self.stat.parameters['targets'] = self.controllableOrd
    self.stat.initialize(runInfo, inputs, initDict)
    self.raiseADebug('GRID INFO:')
    self.raiseADebug(self.gridInfo)
    self.raiseADebug('N-DIMENSIONAL CONTROLLABLE SPACE:')
    self.raiseADebug(self.controllableSpace)
    self.raiseADebug('N-DIMENSIONAL NON-CONTROLLABLE SPACE:')
    self.raiseADebug(self.nonControllableSpace)
    self.raiseADebug('CONTROLLABLE VARIABLES ORDER:')
    self.raiseADebug(self.controllableOrd)
    self.raiseADebug('NON-CONTROLLABLE VARIABLES ORDER:')
    self.raiseADebug(self.nonControllableOrd)
    self.raiseADebug('SURFACE POINTS MATRIX:')
    self.raiseADebug(self.surfPointsMatrix)

  def __gridSetting__(self, constrType = 'equal'):
    for varName in self.controllableGrid.keys():
      if self.controllableGrid[varName][0] == 'value':
        self.__stepError__(float(self.controllableDist[varName].lowerBound), float(self.controllableDist[varName].upperBound), self.controllableGrid[varName][1], self.controllableGrid[varName][2], varName)
        self.gridInfo[varName] = (self.controllableGrid[varName][0], constrType, [float(self.controllableDist[varName].lowerBound) + self.controllableGrid[varName][2] * i for i in range(self.controllableGrid[varName][1] + 1)])
      elif self.controllableGrid[varName][0] == 'CDF':
        self.__stepError__(0, 1, self.controllableGrid[varName][1], self.controllableGrid[varName][2], varName)
        self.gridInfo[varName] = (self.controllableGrid[varName][0], constrType, [self.controllableGrid[varName][2] * i for i in range(self.controllableGrid[varName][1] + 1)])
      else:
        self.raiseAnError(NameError, 'inserted invalid grid type. Only "value" and "CDF" are accepted.')
    for varName in self.nonControllableGrid.keys():
      if self.nonControllableGrid[varName][0] == 'value':
        self.__stepError__(float(self.nonControllableDist[varName].lowerBound), float(self.nonControllableDist[varName].upperBound), self.nonControllableGrid[varName][1], self.nonControllableGrid[varName][2], varName)
        self.gridInfo[varName] = (self.nonControllableGrid[varName][0], constrType, [float(self.nonControllableDist[varName].lowerBound) + self.nonControllableGrid[varName][2] * i for i in range(self.nonControllableGrid[varName][1] + 1)])
      elif self.nonControllableGrid[varName][0] == 'CDF':
        self.__stepError__(0, 1, self.nonControllableGrid[varName][1], self.nonControllableGrid[varName][2], varName)
        self.gridInfo[varName] = (self.nonControllableGrid[varName][0], constrType, [self.nonControllableGrid[varName][2] * i for i in range(self.nonControllableGrid[varName][1] + 1)])
      else:
        self.raiseAnError(NameError, 'inserted invalid grid type. Only "value" and "CDF" are accepted.')

  def __stepError__(self, lowerBound, upperBound, steps, tol, varName):
    if upperBound - lowerBound < steps * tol:
      self.raiseAnError(IOError, 'requested number of steps or tolerance for variable ' + varName + ' exceeds its limit.')

  def __gridGeneration__(self):
    NotchesByVar = [None] * len(self.controllableGrid.keys())
    controllableSpaceSize = None
    for varId, varName in enumerate(self.controllableGrid.keys()):
      NotchesByVar[varId] = self.controllableGrid[varName][1] + 1
      self.controllableOrd.append(varName)
    controllableSpaceSize = tuple(NotchesByVar + [len(self.controllableGrid.keys())])
    self.controllableSpace = np.zeros(controllableSpaceSize)
    iterIndex = ravenArrayIterator(arrayIn=self.controllableSpace)
    while not iterIndex.finished:
      coordIndex = iterIndex.multiIndex[-1]
      varName = list(self.controllableGrid.keys())[coordIndex]
      notchPos = iterIndex.multiIndex[coordIndex]
      if self.gridInfo[varName][0] == 'CDF':
        valList = []
        for probVal in self.gridInfo[varName][2]:
          valList.append(self.controllableDist[varName].cdf(probVal))
        self.controllableSpace[iterIndex.multiIndex] = valList[notchPos]
      else:
        self.controllableSpace[iterIndex.multiIndex] = self.gridInfo[varName][2][notchPos]
      iterIndex.iternext()
    NotchesByVar = [None] * len(self.nonControllableGrid.keys())
    nonControllableSpaceSize = None
    for varId, varName in enumerate(self.nonControllableGrid.keys()):
      NotchesByVar[varId] = self.nonControllableGrid[varName][1] + 1
      self.nonControllableOrd.append(varName)
    nonControllableSpaceSize = tuple(NotchesByVar + [len(self.nonControllableGrid.keys())])
    self.nonControllableSpace = np.zeros(nonControllableSpaceSize)
    iterIndex = ravenArrayIterator(arrayIn=self.nonControllableSpace)
    while not iterIndex.finished:
      coordIndex = iterIndex.multiIndex[-1]
      varName = list(self.nonControllableGrid.keys())[coordIndex]
      notchPos = iterIndex.multiIndex[coordIndex]
      if self.gridInfo[varName][0] == 'CDF':
        valList = []
        for probVal in self.gridInfo[varName][2]:
          valList.append(self.nonControllableDist[varName].cdf(probVal))
        self.nonControllableSpace[iterIndex.multiIndex] = valList[notchPos]
      else:
        self.nonControllableSpace[iterIndex.multiIndex] = self.gridInfo[varName][2][notchPos]
      iterIndex.iternext()

  def inputToInternal(self, currentInput):
    """
     Method to convert an input object into the internal format that is
     understandable by this pp.
     @ In, currentInput, object, an object that needs to be converted
     @ Out, None, the resulting converted object is stored as an attribute of this class
    """
    for item in currentInput:
      if item.type == 'PointSet':
        self.surfPointsMatrix = np.zeros((len(item.getParam('output', item.getParaKeys('outputs')[-1])), len(self.gridInfo.keys()) + 1))
        k = 0
        for varName in self.controllableOrd:
          self.surfPointsMatrix[:, k] = item.getParam('input', varName)
          k += 1
        for varName in self.nonControllableOrd:
          self.surfPointsMatrix[:, k] = item.getParam('input', varName)
          k += 1
        self.surfPointsMatrix[:, k] = item.getParam('output', item.getParaKeys('outputs')[-1])

  def run(self, Input):
    """
     This method executes the postprocessor action. In this case, it computes the safest point
     @ In,  Input, object, object contained the data to process. (inputToInternal output)
     @ Out, PointSet, PointSet containing the elaborated data
    """
    nearestPointsInd = []
    dataCollector = DataObjects.returnInstance('PointSet', self)
    dataCollector.type = 'PointSet'
    surfTree = spatial.KDTree(copy.copy(self.surfPointsMatrix[:, 0:self.surfPointsMatrix.shape[-1] - 1]))
    self.controllableSpace.shape = (np.prod(self.controllableSpace.shape[0:len(self.controllableSpace.shape) - 1]), self.controllableSpace.shape[-1])
    self.nonControllableSpace.shape = (np.prod(self.nonControllableSpace.shape[0:len(self.nonControllableSpace.shape) - 1]), self.nonControllableSpace.shape[-1])
    self.raiseADebug('RESHAPED CONTROLLABLE SPACE:')
    self.raiseADebug(self.controllableSpace)
    self.raiseADebug('RESHAPED NON-CONTROLLABLE SPACE:')
    self.raiseADebug(self.nonControllableSpace)
    for ncLine in range(self.nonControllableSpace.shape[0]):
      queryPointsMatrix = np.append(self.controllableSpace, np.tile(self.nonControllableSpace[ncLine, :], (self.controllableSpace.shape[0], 1)), axis = 1)
      self.raiseADebug('QUERIED POINTS MATRIX:')
      self.raiseADebug(queryPointsMatrix)
      nearestPointsInd = surfTree.query(queryPointsMatrix)[-1]
      distList = []
      indexList = []
      probList = []
      for index in range(len(nearestPointsInd)):
        if self.surfPointsMatrix[np.where(np.prod(surfTree.data[nearestPointsInd[index], 0:self.surfPointsMatrix.shape[-1] - 1] == self.surfPointsMatrix[:, 0:self.surfPointsMatrix.shape[-1] - 1], axis = 1))[0][0], -1] == 1:
          distList.append(np.sqrt(np.sum(np.power(queryPointsMatrix[index, 0:self.controllableSpace.shape[-1]] - surfTree.data[nearestPointsInd[index], 0:self.controllableSpace.shape[-1]], 2))))
          indexList.append(index)
      if distList == []:
        self.raiseAnError(ValueError, 'no safest point found for the current set of non-controllable variables: ' + str(self.nonControllableSpace[ncLine, :]) + '.')
      else:
        for cVarIndex in range(len(self.controllableOrd)):
          dataCollector.updateInputValue(self.controllableOrd[cVarIndex], copy.copy(queryPointsMatrix[indexList[distList.index(max(distList))], cVarIndex]))
        for ncVarIndex in range(len(self.nonControllableOrd)):
          dataCollector.updateInputValue(self.nonControllableOrd[ncVarIndex], copy.copy(queryPointsMatrix[indexList[distList.index(max(distList))], len(self.controllableOrd) + ncVarIndex]))
          if queryPointsMatrix[indexList[distList.index(max(distList))], len(self.controllableOrd) + ncVarIndex] == self.nonControllableDist[self.nonControllableOrd[ncVarIndex]].lowerBound:
            if self.nonControllableGrid[self.nonControllableOrd[ncVarIndex]][0] == 'CDF':
              prob = self.nonControllableGrid[self.nonControllableOrd[ncVarIndex]][2] / float(2)
            else:
              prob = self.nonControllableDist[self.nonControllableOrd[ncVarIndex]].cdf(self.nonControllableDist[self.nonControllableOrd[ncVarIndex]].lowerBound + self.nonControllableGrid[self.nonControllableOrd[ncVarIndex]][2] / float(2))
          elif queryPointsMatrix[indexList[distList.index(max(distList))], len(self.controllableOrd) + ncVarIndex] == self.nonControllableDist[self.nonControllableOrd[ncVarIndex]].upperBound:
            if self.nonControllableGrid[self.nonControllableOrd[ncVarIndex]][0] == 'CDF':
              prob = self.nonControllableGrid[self.nonControllableOrd[ncVarIndex]][2] / float(2)
            else:
              prob = 1 - self.nonControllableDist[self.nonControllableOrd[ncVarIndex]].cdf(self.nonControllableDist[self.nonControllableOrd[ncVarIndex]].upperBound - self.nonControllableGrid[self.nonControllableOrd[ncVarIndex]][2] / float(2))
          else:
            if self.nonControllableGrid[self.nonControllableOrd[ncVarIndex]][0] == 'CDF':
              prob = self.nonControllableGrid[self.nonControllableOrd[ncVarIndex]][2]
            else:
              prob = self.nonControllableDist[self.nonControllableOrd[ncVarIndex]].cdf(queryPointsMatrix[indexList[distList.index(max(distList))], len(self.controllableOrd) + ncVarIndex] + self.nonControllableGrid[self.nonControllableOrd[ncVarIndex]][2] / float(2)) - self.nonControllableDist[self.nonControllableOrd[ncVarIndex]].cdf(queryPointsMatrix[indexList[distList.index(max(distList))], len(self.controllableOrd) + ncVarIndex] - self.nonControllableGrid[self.nonControllableOrd[ncVarIndex]][2] / float(2))
          probList.append(prob)
      dataCollector.updateOutputValue('Probability', np.prod(probList))
      dataCollector.updateMetadata('ProbabilityWeight', np.prod(probList))
    dataCollector.updateMetadata('ExpectedSafestPointCoordinates', self.stat.run(dataCollector)['expectedValue'])
    self.raiseADebug(dataCollector.getParametersValues('input'))
    self.raiseADebug(dataCollector.getParametersValues('output'))
    self.raiseADebug(dataCollector.getMetadata('ExpectedSafestPointCoordinates'))
    return dataCollector

  def collectOutput(self, finishedjob, output):
    """
      Function to place all of the computed data into the output object
      @ In, finishedJob: A JobHandler object that is in charge of running this
                         post-processor
      @ In, output: The object where we want to place our computed results
      @ Out, None
    """
    if finishedjob.returnEvaluation() == -1:
      self.raiseAnError(RuntimeError, 'no available output to collect (the run is likely not over yet).')
    else:
      dataCollector = finishedjob.returnEvaluation()[1]
      if output.type != 'PointSet':
        self.raiseAnError(TypeError, 'output item type must be "PointSet".')
      else:
        if not output.isItEmpty():
          self.raiseAnError(ValueError, 'output item must be empty.')
        else:
          for key, value in dataCollector.getParametersValues('input').items():
            for val in value: output.updateInputValue(key, val)
          for key, value in dataCollector.getParametersValues('output').items():
            for val in value: output.updateOutputValue(key, val)
          for key, value in dataCollector.getAllMetadata().items(): output.updateMetadata(key, value)
#
#
#
class ComparisonStatistics(BasePostProcessor):
  """
  ComparisonStatistics is to calculate statistics that compare
  two different codes or code to experimental data.
  """

  class CompareGroup:
    def __init__(self):
      """
       Constructor
      """
      self.dataPulls = []
      self.referenceData = {}

  def __init__(self, messageHandler):
    """
     Constructor
     @ In, messageHandler, message handler object
    """
    BasePostProcessor.__init__(self, messageHandler)
    self.dataDict = {}  # Dictionary of all the input data, keyed by the name
    self.compareGroups = []  # List of each of the groups that will be compared
    # self.dataPulls = [] #List of data references that will be used
    # self.referenceData = [] #List of reference (experimental) data
    self.methodInfo = {}  # Information on what stuff to do.
    self.fZStats = False
    self.interpolation = "linear"
    self.requiredAssObject = (True, (['Distribution'], ['-n']))
    self.distributions = {}
    
    
    
    ##To be able to call the BasicStatistics.run method to get the stats.
    self.BS = BasicStatistics(BasePostProcessor)
    self.BS.__init__(messageHandler)
    self.dimensionVariable = []
    self.voronoi = False
    self.inputsVoronoi = []
    self.outputsVoronoi = []
    self.dimensionVornoi = []
    self.spaceVoronoi = []

  def inputToInternal(self, currentInput):
    """
     Method to convert an input object into the internal format that is
     understandable by this pp.
     @ In, currentInput, object, an object that needs to be converted
     @ Out, object, the resulting converted object
    """
    return [(currentInput)]

  def initialize(self, runInfo, inputs, initDict):
    """
     Method to initialize the ComparisonStatistics pp.
     @ In, runInfo, dict, dictionary of run info (e.g. working dir, etc)
     @ In, inputs, list, list of inputs
     @ In, initDict, dict, dictionary with initialization options
    """
    BasePostProcessor.initialize(self, runInfo, inputs, initDict)

  def _localReadMoreXML(self, xmlNode):
    """
    Function to read the portion of the xml input that belongs to this specialized class
    and initialize some stuff based on the inputs got
    @ In, xmlNode    : Xml element node
    @ Out, None
    """
    for outer in xmlNode:
      if outer.tag == 'compare':
        compareGroup = ComparisonStatistics.CompareGroup()
        for child in outer:
          if child.tag == 'data':
            dataName = child.text
            splitMulti = dataName.split(",")
            temp =[]
            for dimension in splitMulti:
              splitName = dimension.split("|")
              name, kind = splitName[:2]
              rest = splitName[2:]
              temp.append([name,kind,rest])
            compareGroup.dataPulls.append(temp)
          elif child.tag == 'reference':
            # This has name=distribution
            compareGroup.referenceData = dict(child.attrib)
            if "name" not in compareGroup.referenceData:
              self.raiseAnError(IOError, 'Did not find name in reference block')
        self.compareGroups.append(compareGroup)
      if outer.tag == 'kind':
        self.methodInfo['kind'] = outer.text
        if 'numBins' in outer.attrib:
          self.methodInfo['numBins'] = int(outer.attrib['numBins'])
        if 'binMethod' in outer.attrib:
          self.methodInfo['binMethod'] = outer.attrib['binMethod'].lower()
          if self.methodInfo['binMethod']=='voronoi':
            self.voronoi = True
            for child in outer.attrib:
              if child.lower()=="inputs"  : self.inputsVoronoi  = outer.attrib['inputs'].split(',') 
              if child.lower()=="outputs" : self.outputsVoronoi = outer.attrib['outputs'].split(',')
              if child.lower()=="space"   : self.spaceVoronoi   = outer.attrib['space'].split(',')
            if outer.text.lower()=="unidimensional"    : self.dimensionVoronoi = "unidimensional"
            elif outer.text.lower()=="multidimensional": self.raiseAnError(IOError,"multidimensionnal not yet implemented for comparison statistics")#self.dimensionVornoi = "multidimensional"
            else                                       : self.raiseAnError(IOError,"Unknown text : " + child.text.lower() + " .Expecting unidimensional or multidimensional.")
          else:
            self.voronoi = False
      if outer.tag == 'fz':
        self.fZStats = (outer.text.lower() in utils.stringsThatMeanTrue())
      if outer.tag == 'interpolation':
        interpolation = outer.text.lower()
        if interpolation == 'linear':
          self.interpolation = 'linear'
        elif interpolation == 'quadratic':
          self.interpolation = 'quadratic'
        else:
          self.raiseADebug('unexpected interpolation method ' + interpolation)
          self.interpolation = interpolation
    for i in self.compareGroups:
      self.dimensionVariable.append(len(i.dataPulls[0]))
    

  def _localGenerateAssembler(self, initDict):
    self.distributions = initDict.get('Distributions', {})
  

  def run(self,Input):
    """
    This method executes the postprocessor action. In this case, it computes some statistical
    data as well as the comparison metrics.
    @ In, Input, object, object containing the data to proces. (inputToInternal output)
    @ Out, outputDict, dictionnary, dictionnary in witch are stored the compted data.
    """
    if self.voronoi:
      outputDict = self.compareData1D(Input)
      return outputDict
    outputDict = {}
    dataDict = {}
    for aInput in Input: dataDict[aInput.name] = aInput
    self.dataDict = dataDict
    dataToProcess = []    
    for compareGroup in self.compareGroups:
      dataPulls = compareGroup.dataPulls
      reference = compareGroup.referenceData
      foundDataObjects = []
      #self.dataDict : the input data should be able to be multidimensionnal. (a numpy array of a list of pointCoordinate. Cf np.random.rand(10,4))
      coordTemp=[]
      for distribution in dataPulls:
        for coord in distribution:
          for name, kind, rest in [coord]:
            data = self.dataDict[name].getParametersValues(kind)
            if len(rest) == 1:
              foundDataObjects.append(data[rest[0]])
              coordTemp.append(coord)
      dataToProcess.append((coordTemp, foundDataObjects, reference))
    for dataPulls, datas, reference in dataToProcess:
      compareGroupName = '__'.join([dataPulls[i][2][0] for i in range(len(dataPulls))])
      outputDict[compareGroupName] = {}
      graphData = []
      if "name" in reference:
        distributionName = reference["name"]
        if not distributionName in self.distributions:
          self.raiseAnError(IOError, 'Did not find ' + distributionName +
                             ' in ' + str(self.distributions.keys()))
        else:
          distribution = self.distributions[distributionName]
        refDataStats = {"mean":distribution.untruncatedMean(),
                        "stdev":distribution.untruncatedStdDev()}
        refDataStats["minBinSize"] = refDataStats["stdev"] / 2.0
        refPdf = lambda x:distribution.pdf(x)
        refCdf = lambda x:distribution.cdf(x)
        graphData.append((refDataStats, refCdf, refPdf, "ref_" + distributionName))
      listTarget = []
      for dataPull, data in zip(dataPulls, datas):
        ##Creation of the input for the BasicStatistics class.
        InputIn = {'targets':{}, 'metadata':{'Boundaries':np.array([{dataPull[-1][0]:(-sys.float_info.max,sys.float_info.max)}])}}
        InputIn['targets'][str(dataPull[-1][0])] = data
        parameterSet = [dataPull[-1][0]]
        listTarget.append(dataPull[-1][0])
        voronoi = self.voronoi  #Utile ?
        self.BS.initializeComparison(voronoi,parameterSet)
        dataStats = self.processData(dataPull, data, self.methodInfo)
        dataKeys = set(dataStats.keys())
        counts = dataStats['counts']
        bins = dataStats['bins']
        countSum = sum(counts)
        binBoundaries = [dataStats['low']] + bins + [dataStats['high']]
        outputDict[compareGroupName][dataPull[-1][0]] =  {}
        outputDict[compareGroupName][dataPull[-1][0]]["dataPull"] = str(dataPull)
        outputDict[compareGroupName][dataPull[-1][0]]["numBins"] = dataStats['numBins']
        outputDict[compareGroupName][dataPull[-1][0]].update(dict.fromkeys(["binBoundary","binMidpoint","binCount","normalizedBinCount","f_prime","cdf"],[]))
        cdf = [0.0] * len(counts)
        midpoints = [0.0] * len(counts)
        cdfSum = 0.0
        for i in range(len(counts)):
          f0 = counts[i] / countSum
          cdfSum += f0
          cdf[i] = cdfSum
          midpoints[i] = (binBoundaries[i] + binBoundaries[i + 1]) / 2.0
        cdfFunc = mathUtils.createInterp(midpoints, cdf, 0.0, 1.0, self.interpolation)
        fPrimeData = [0.0] * len(counts)
        outputDict[compareGroupName][dataPull[-1][0]].update(dict(zip(["binBoundary","binMidpoint","binCount","normalizedBinCount","f_prime","cdf"],[[],[],[],[],[],[]])))
        for i in range(len(counts)):
          h = binBoundaries[i + 1] - binBoundaries[i]
          nCount = counts[i] / countSum  # normalized count
          f0 = cdf[i]
          if i + 1 < len(counts):
            f1 = cdf[i + 1]
          else:
            f1 = 1.0
          if i + 2 < len(counts):
            f2 = cdf[i + 2]
          else:
            f2 = 1.0
          if self.interpolation == 'linear':
            fPrime = (f1 - f0) / h
          else:
            fPrime = (-1.5 * f0 + 2.0 * f1 + -0.5 * f2) / h
          fPrimeData[i] = fPrime
          outputDict[compareGroupName][dataPull[-1][0]]["binBoundary"].append(binBoundaries[i + 1])
          outputDict[compareGroupName][dataPull[-1][0]]["binMidpoint"].append(midpoints[i])
          outputDict[compareGroupName][dataPull[-1][0]]["binCount"].append(counts[i])
          outputDict[compareGroupName][dataPull[-1][0]]["normalizedBinCount"].append(nCount)
          outputDict[compareGroupName][dataPull[-1][0]]["f_prime"].append(fPrime)
          outputDict[compareGroupName][dataPull[-1][0]]["cdf"].append(cdf[i])
        pdfFunc = mathUtils.createInterp(midpoints, fPrimeData, 0.0, 0.0, self.interpolation)
        dataKeys -= set({'numBins', 'counts', 'bins'})
        for key in dataKeys:
          outputDict[compareGroupName][dataPull[-1][0]][key] = dataStats[key]
        self.raiseADebug("dataStats: " + str(dataStats))
        graphData.append((dataStats, cdfFunc, pdfFunc, str(dataPull)))
      graphDataDict = mathUtils.getGraphs(graphData, self.fZStats)
      outputDict[compareGroupName]["graphDataDict"] = graphDataDict
      outputDict[compareGroupName]["graphData"    ] = graphData
    return outputDict



  def collectOutput(self, finishedjob, output):
    """
    Function to place all of the computed data into the output object
    @ In, output: the object where we want to place our computed data
    @ In, finishedjob: A JobHandler object that is in charge of runnig this post-processor
    @ Out, None
    """
    self.raiseADebug("finishedjob: " + str(finishedjob) + ", output " + str(output))
    if finishedjob.returnEvaluation() == -1: self.raiseAnError(RuntimeError, ' No available Output to collect (Run probabably is not finished yet)')
    outputDict = finishedjob.returnEvaluation()[1]   #Possible que pas le bon dic
    generateCSV = False
    generatePointSet = False
    if isinstance(output,Files.File):
      generateCSV = True
    elif output.type == 'PointSet':
      generatePointSet = True
    else:
      self.raiseAnError(IOError, 'unsupported type ' + str(type(output)))
    if generateCSV:
      csv = output
    if generateCSV:
      for compareKey in outputDict.keys():
        targets = compareKey.split("__")
        for target in targets:
          utils.printCsv(csv, '"' + outputDict[compareKey][target]["dataPull"] + '"' )
          utils.printCsv(csv, '"numBins"', outputDict[compareKey][target]["numBins"])
          utils.printCsv(csv, '"binBoundary"', '"binMidpoint"', '"binCount"', '"normalizedBinCount"', '"f_prime"', '"cdf"')
          for i in range(len(outputDict[compareKey][target]["binCount"])):
            utils.printCsv(csv, outputDict[compareKey][target]["binBoundary"][i], outputDict[compareKey][target]["binMidpoint"][i],
             outputDict[compareKey][target]["binCount"][i], outputDict[compareKey][target]["normalizedBinCount"][i],
             outputDict[compareKey][target]["f_prime"][i], outputDict[compareKey][target]["cdf"][i])
          keyList = set(outputDict[compareKey][target].keys())
          keyList -= set({"binBoundary","binCount","f_prime","cdf","normalizedBinCount","binMidpoint"})
          for key in keyList:
            utils.printCsv(csv, '"' + key + '"',outputDict[compareKey][target][key])
        keyList = set(outputDict[compareKey].keys())
        keyList -= set({target[0],target[1]})
        for key in keyList:
          if type(outputDict[compareKey][key]).__name__ == 'list':
            utils.printCsv(csv, *([]))
        graphDataDict = outputDict[compareKey]["graphDataDict"]
        for key in graphDataDict:
          value = graphDataDict[key]
          if type(value).__name__ == 'list':
            utils.printCsv(csv, *(['"' + l[0] + '"' for l in value]))
            for i in range(1, len(value[0])):
              utils.printCsv(csv, *([l[i] for l in value]))
          else:
            utils.printCsv(csv, '"' + key + '"', value)  
        graphData = outputDict[compareKey]["graphData"]
        for i in range(len(graphData)):
          dataStat = graphData[i][0]
          def delist(l):
            if type(l).__name__ == 'list':
              return '_'.join([delist(x) for x in l])
            else:
              return str(l)
          newFileName = output.getBase() + "_" + delist(target) + "_" + str(i) + ".csv"
          if type(dataStat).__name__ != 'dict':
            assert(False)
            continue
          dataPairs = []
          for key in sorted(dataStat.keys()):
            value = dataStat[key]
            if np.isscalar(value):
              dataPairs.append((key, value))
          extraCsv = Files.returnInstance('CSV',self)
          extraCsv.initialize(newFileName,self.messageHandler)
          extraCsv.open("w")
          extraCsv.write(",".join(['"' + str(x[0]) + '"' for x in dataPairs]))
          extraCsv.write("\n")
          extraCsv.write(",".join([str(x[1]) for x in dataPairs]))
          extraCsv.write("\n")
          extraCsv.close()
        utils.printCsv(csv)
    if generatePointSet:
      for compareKey in outputDict.keys():
        graphDataDict = outputDict[compareKey]["graphDataDict"]
        for key in graphDataDict:
          value = graphDataDict[key]
          if type(value).__name__ == 'list':
            for i in range(len(value)):
              subvalue = value[i]
              name = subvalue[0]
              subdata = subvalue[1:]
              if i == 0:
                output.updateInputValue(name, subdata)
              else:
                output.updateOutputValue(name, subdata)
            break  # XXX Need to figure out way to specify which data to return

  def compareData1D(self, Input):
    """
    This method executes the postprocessor action. In this case, it computes some statistical
    data as well as the comparison metrics using the voronoi tessellation.
    @ In, Input, object, object containing the data to proces. (inputToInternal output)
    @ Out, outputDict, dictionnary, dictionnary in witch are stored the compted data.
    """
    outputDict = {}
    dataDict = {}
    inputDict = {'targets':{}, 'metadata':{}}
    if type(Input) == list  : currentInput = Input [-1]
    else                         : currentInput = Input
    if hasattr(currentInput,'type'):
      inType = currentInput.type
    if inType not in ['PointSet']:
      self.raiseAnError(IOError, self, 'ComparisonStatistics postprocessor with Voronoi accepts PointSet only ! Got ' + str(inType) + '!')
    if inType in ['PointSet']:
      inputDict['metadata'] = currentInput.getAllMetadata()
    dictCDFs = {}
    for target in self.inputsVoronoi:
      dictCDFs[target] = [[inputDict['metadata']['SampledVarsCdf'][i][target]]  for i in range(len(inputDict['metadata']['SampledVarsCdf']))]
    for aInput in Input: dataDict[aInput.name] = aInput
    self.dataDict = dataDict
    dataToProcess = []
    for compareGroup in self.compareGroups:
      dataPulls = compareGroup.dataPulls
      reference = compareGroup.referenceData
      foundDataObjects = []
      #self.dataDict : the input data should be able to be multidimensionnal. (a numpy array of a list of pointCoordinate. Cf np.random.rand(10,4))
      coordTemp=[]
      
      for distribution in dataPulls:
        for coord in distribution:
          for name, kind, rest in [coord]:
            data = self.dataDict[name].getParametersValues(kind)
            if len(rest) == 1:
              foundDataObjects.append(data[rest[0]])
              coordTemp.append(coord)
      dataToProcess.append((coordTemp, foundDataObjects, reference))
    for dataPulls, datas, reference in dataToProcess:
      compareGroupName = '__'.join([dataPulls[i][2][0] for i in range(len(dataPulls))])
      outputDict[compareGroupName] = {}
      graphData = []
      if "name" in reference:
        distributionName = reference["name"]
        if not distributionName in self.distributions:
          self.raiseAnError(IOError, 'Did not find ' + distributionName +
                             ' in ' + str(self.distributions.keys()))
        else:
          distribution = self.distributions[distributionName]
        refDataStats = {"expectedValue":{distributionName:distribution.untruncatedMean()},
                        "sigma":{distributionName:distribution.untruncatedStdDev()}}
        refDataStats["minBinSize"] = refDataStats["sigma"].values()[0] / 2.0
        refPdf = lambda x:distribution.pdf(x)
        refCdf = lambda x:distribution.cdf(x)
        graphData.append((refDataStats, refCdf, refPdf, "ref_" + distributionName))
      listTarget = []
      for dataPull, data in zip(dataPulls, datas):
        ##Creation of the input for the BasicStatistics class.
        InputIn = {'targets':{}, 'metadata':{'Boundaries':np.array([{dataPull[-1][0]:(-sys.float_info.max,sys.float_info.max)}])}}
        InputIn['targets'][str(dataPull[-1][0])] = data
        parameterSet = [dataPull[-1][0]]
        listTarget.append(dataPull[-1][0])
        voronoi = self.voronoi
        InputIn['metadata']['SampledVarsCdf'] = inputDict['metadata']['SampledVarsCdf']
        self.BS.initializeComparison(voronoi,parameterSet,self.inputsVoronoi,self.outputsVoronoi)
        dataStats2 = BasicStatistics.run(self.BS,InputIn)
        self.proba = self.BS.returnProbaComparison()
        proba = self.proba[dataPull[-1][0]]
        toSort = np.column_stack((data,proba))
        sortedCouple = sorted(toSort, key = lambda x: float(x[0]))
        midpoints = [sortedCouple[i][0] for i in range(len(data))]
        proba = [sortedCouple[i][1] for i in range(len(data))]
        dataKeys = set(dataStats2.keys())
        todelete=[]
        i = 0
        while i <len(midpoints)-1:
          p = 1
          while (i+p<len(midpoints)) and (str(midpoints[i])==str(midpoints[i+p])):
            todelete.append(i+p)
            proba[i]+=proba[i+p]
            p+=1
          i+=p
        midpoints = np.delete(midpoints,todelete)    
        todelete.reverse()
        for i in todelete:
          del proba[i]
        counts = proba
        countSum = sum(counts)        
        binBoundaries = [0.0]*(len(midpoints)+1)
        outputDict[compareGroupName][dataPull[-1][0]] =  {}
        outputDict[compareGroupName][dataPull[-1][0]]["dataPull"] = str(dataPull)
        outputDict[compareGroupName][dataPull[-1][0]]["numBins"] = 0
        outputDict[compareGroupName][dataPull[-1][0]].update(dict.fromkeys(["binBoundary","binMidpoint","binCount","normalizedBinCount","f_prime","cdf"],[]))
        cdf = [0.0] * len(midpoints)
        cdfSum = 0.0
        nCount = [0.0]*len(midpoints)
        for j in range(len(midpoints)):
          f0 = proba[j]
          nCount[j] = f0
          cdfSum+=f0
          cdf[j] = cdfSum
          if j ==len(midpoints)-1:
            binBoundaries[j+1] = midpoints[j] + (midpoints[j]+midpoints[j-1])/2
          else:
            binBoundaries[j+1] = (midpoints[j]+midpoints[j+1])/2.0
        binBoundaries[0] = midpoints[1] - (midpoints[0]+midpoints[1])/2
        bins=binBoundaries
        counts=nCount
        cdfFunc = mathUtils.createInterpV2(midpoints, cdf, 0.0, 1.0, self.interpolation, tyype='CDF')
        fPrimeData = [0.0] * len(midpoints)
        outputDict[compareGroupName][dataPull[-1][0]].update(dict(zip(["binBoundary","binMidpoint","binCount","normalizedBinCount","f_prime","cdf"],[[],[],[],[],[],[]])))
        for i in range(len(midpoints)):
          h = binBoundaries[i + 1] - binBoundaries[i]
          f0 = cdf[i]
          if i + 1 < len(bins)-1:
            f1 = cdf[i + 1]
          else:
            f1 = 1.0
          if i + 2 < len(bins)-1:
            f2 = cdf[i + 2]
          else:
            f2 = 1.0
          if self.interpolation == 'linear':
            fPrime = (f1 - f0) / h
          else:
            fPrime = (-1.5 * f0 + 2.0 * f1 + -0.5 * f2) / h
          fPrimeData[i] = fPrime
          outputDict[compareGroupName][dataPull[-1][0]]["binBoundary"].append(binBoundaries[i + 1])
          outputDict[compareGroupName][dataPull[-1][0]]["binMidpoint"].append(midpoints[i])
          outputDict[compareGroupName][dataPull[-1][0]]["binCount"].append(counts[i])
          outputDict[compareGroupName][dataPull[-1][0]]["normalizedBinCount"].append(nCount[i])
          outputDict[compareGroupName][dataPull[-1][0]]["f_prime"].append(fPrime)
          outputDict[compareGroupName][dataPull[-1][0]]["cdf"].append(cdf[i])
        pdfFunc = mathUtils.createInterpV2(midpoints, fPrimeData, 0.0, 0.0, self.interpolation, tyype='PDF')
        dataKeys -= set({'numBins', 'counts', 'bins'})
        for key in dataKeys:
          outputDict[compareGroupName][dataPull[-1][0]][key] = dataStats2[key]
        self.raiseADebug("dataStats: " + str(dataStats2))
        dataStats2["minBinSize"] =  min([binBoundaries[j+1]-binBoundaries[j] for j in range(len(bins)-1)])
        graphData.append((dataStats2, cdfFunc, pdfFunc, str(dataPull)))
      graphDataDict = mathUtils.getGraphs(graphData, self.fZStats)
      outputDict[compareGroupName]["graphDataDict"] = graphDataDict
      outputDict[compareGroupName]["graphData"    ] = graphData
    return outputDict

        
  def compareDataC(self,points,proba): #Not implemented yet
    """
    Method to interpolate the pdf and compute some stats (mean, covariance) 
    @In, points, array-like,list of input points
    @In, proba, array-like,list of probability weight
    """
    mini = {}
    maxi = {}
    grid = {}
    listMean = {}
    a = int(len(points)**(1.0/self.dimension))
    for p in range(self.dimension):
      mini.setdefault(p+1,[])
      maxi.setdefault(p+1,[])
      grid.setdefault(p+1,[])
      mini[p+1] = points2[:,p].min()
      maxi[p+1] = points2[:,p].max()
      grid[p+1] = np.linspace(mini[p+1],maxi[p+1],a)
    
    ##Nearet interpolation with gap filled at 0
    cvh = ConvexHull(petiteEnveloppe)
    def createNearestInterpolation(points,proba,cvh):
      inter3 = interpolate.NearestNDInterpolator(points,proba)
      ppoints = np.asarray(points)
      #inter3 = interpolate.Rbf(ppoints[:,0].tolist(),ppoints[:,1].tolist(),proba)
      b = cvh.equations.tolist()
      def myInterp(points):
        if type(points) is not list:
          a = points.tolist()+[1]
        else:
          a = points +[1]
        if (any(np.dot(a,b[p])>0 for p in range(len(b)))):
          return 0
        else:
          return inter3(points)
          #return inter3(points[0],points[1])
      return myInterp
    inter3 = createNearestInterpolation(points,proba,cvh)    
    minima = [(lambda x: (lambda y: mini[x+1]))(i) for i in range(len(mini))]
    maxima = [(lambda x: (lambda y: maxi[x+1]))(i) for i in range(len(maxi))]
    integra = [0.0]*len(mini)    
    def make_integranda(p):
      def f(*arg):
        return arg[p]*inter3([i for i in arg]) 
      return f
    def make_intepdf():
      def f(*arg):
        return inter3([i for i in arg])
      return f
    def make_inteCoord():
      def f(*arg):
        A = 1
        for p in arg:
          A*=p
        return A*inter3([i for i in arg])
      return f
    def integrand3(x,y):
      return x*y*inter3([x,y])
    integrapdf = make_intepdf()
    for p in range(len(mini)):
      f = make_integranda(p)
      integra[p]=f
    inteCoord = make_inteCoord()
    options =[]
    for p in range(self.dimension):
      options.append({'limit':50})
    iint2 = integrate.nquad(integrapdf,[[mini[i+1],maxi[i+1]] for i in range(len(mini))],opts = options)
    for p in range(self.dimension):
      listMean.setdefault(p+1,[])
      listMean[p+1] = (integrate.nquad(integra[p],[[mini[i+1],maxi[i+1]] for i in range(len(mini))],opts=options))
      listMean[p+1] = [listMean[p+1][0]/iint2[0],listMean[p+1][1]]
    intxxx3 = (integrate.nquad(inteCoord,[[mini[i+1],maxi[i+1]] for i in range(len(mini))],opts=options))
    intxxx3 = [intxxx3[0]/iint2[0],intxxx3[1]]
    
  
  def processData(self, dataPull, data, methodInfo):
      """
      Method to bin the data and compute some statisticals informations 
      (that are only relevant if the distribution is normal ?)
      @In, dataPull, 
      @In, data, 
      @In, methodInfo, Dictionnary containing informations on the binning method to use.
      @Out, ret, Dictionnary in which are saved the computed data. (including the binning informations)
      """
      ret = {}
      if hasattr(data,'tolist'):
        sortedData = data.tolist()
      else:
        sortedData = list(data)
      sortedData.sort()
      low = sortedData[0]
      high = sortedData[-1]
      dataRange = high - low
      ret['low'] = low
      ret['high'] = high
      if not 'binMethod' in methodInfo:
        numBins = methodInfo.get("numBins", 10)
      else:
        binMethod = methodInfo['binMethod']
        dataN = len(sortedData)
        if binMethod == 'square-root':
          numBins = int(math.ceil(math.sqrt(dataN)))
        elif binMethod == 'sturges':
          numBins = int(math.ceil(mathUtils.log2(dataN) + 1))
        #elif binMethod == "voronoi":
          
        else:
          self.raiseADebug("Unknown binMethod " + binMethod, 'ExceptedError')
          numBins = 5
      ret['numBins'] = numBins
      kind = methodInfo.get("kind", "uniformBins")
      if kind == "uniformBins":
        bins = [low + x * dataRange / numBins for x in range(1, numBins)]
        ret['minBinSize'] = dataRange / numBins
      elif kind == "equalProbability":
        stride = len(sortedData) // numBins
        bins = [sortedData[x] for x in range(stride - 1, len(sortedData) - stride + 1, stride)]
        if len(bins) > 1:
          ret['minBinSize'] = min(map(lambda x, y: x - y, bins[1:], bins[:-1]))
        else:
          ret['minBinSize'] = dataRange
      counts = mathUtils.countBins(sortedData, bins)
      ret['bins'] = bins
      ret['counts'] = counts
      ret.update(mathUtils.calculateStats(sortedData))
      skewness = ret["skewness"]
      delta = math.sqrt((math.pi / 2.0) * (abs(skewness) ** (2.0 / 3.0)) /
                        (abs(skewness) ** (2.0 / 3.0) + ((4.0 - math.pi) / 2.0) ** (2.0 / 3.0)))
      delta = math.copysign(delta, skewness)
      alpha = delta / math.sqrt(1.0 - delta ** 2)
      variance = ret["sampleVariance"]
      omega = variance / (1.0 - 2 * delta ** 2 / math.pi)
      mean = ret['mean']
      xi = mean - omega * delta * math.sqrt(2.0 / math.pi)
      ret['alpha'] = alpha
      ret['omega'] = omega
      ret['xi'] = xi
      return ret
#
#
#
class PrintCSV(BasePostProcessor):
  """
  PrintCSV PostProcessor class. It prints a CSV file loading data from a hdf5 database or other sources
  """
  def __init__(self, messageHandler):
    """
     Constructor
     @ In, messageHandler, message handler object
    """
    BasePostProcessor.__init__(self, messageHandler)
    self.paramters = ['all']
    self.inObj = None
    self.workingDir = None
    self.printTag = 'POSTPROCESSOR PRINTCSV'

  def inputToInternal(self, currentInput):
    """
     Method to convert an input object into the internal format that is
     understandable by this pp.
     @ In, currentInput, object, an object that needs to be converted
     @ Out, None, the resulting converted object is stored as an attribute of this class
    """
    return [(currentInput)]

  def initialize(self, runInfo, inputs, initDict):
    """
     Method to initialize the PrintCSV pp. In here, the workingdir is collected and eventually created
     @ In, runInfo, dict, dictionary of run info (e.g. working dir, etc)
     @ In, inputs, list, list of inputs
     @ In, initDict, dict, dictionary with initialization options
    """
    BasePostProcessor.initialize(self, runInfo, inputs, initDict)
    self.workingDir = os.path.join(runInfo['WorkingDir'], runInfo['stepName'])  # generate current working dir
    runInfo['TempWorkingDir'] = self.workingDir
    try:                            os.mkdir(self.workingDir)
    except:                         self.raiseAWarning('current working dir ' + self.workingDir + ' already exists, this might imply deletion of present files')
    # if type(inputs[-1]).__name__ == "HDF5" : self.inObj = inputs[-1]      # this should go in run return but if HDF5, it is not pickable

  def _localReadMoreXML(self, xmlNode):
    """
    Function to read the portion of the xml input that belongs to this specialized class
    and initialize some stuff based on the inputs got
    @ In, xmlNode    : Xml element node
    @ Out, None
    """
    for child in xmlNode:
      if child.tag == 'parameters':
        param = child.text
        if(param.lower() != 'all'): self.paramters = param.strip().split(',')
        else: self.paramters[param]

  def collectOutput(self, finishedjob, output):
    """
      Function to place all of the computed data into the output object
      @ In, finishedJob: A JobHandler object that is in charge of running this
                         post-processor
      @ In, output: The object where we want to place our computed results
      @ Out, None
    """
    # Check the input type
    if finishedjob.returnEvaluation() == -1: self.raiseAnError(RuntimeError, 'No available Output to collect (Run probabably is not finished yet)')
    self.inObj = finishedjob.returnEvaluation()[1]
    if(self.inObj.type == "HDF5"):
      #  Input source is a database (HDF5)
      #  Retrieve the ending groups' names
      endGroupNames = self.inObj.getEndingGroupNames()
      HistorySet = {}

      #  Construct a dictionary of all the HistorySet
      for index in range(len(endGroupNames)): HistorySet[endGroupNames[index]] = self.inObj.returnHistory({'history':endGroupNames[index], 'filter':'whole'})
      #  If file, split the strings and add the working directory if present
      for key in HistorySet:
        #  Loop over HistorySet
        #  Retrieve the metadata (posion 1 of the history tuple)
        attributes = HistorySet[key][1]
        #  Construct the header in csv format (first row of the file)
        headers = b",".join([HistorySet[key][1]['outputSpaceHeaders'][i] for i in
                             range(len(attributes['outputSpaceHeaders']))])
        #  Construct history name
        hist = key
        #  If file, split the strings and add the working directory if present
        if self.workingDir:
          output.setPath(self.workingDir)
          # original if os.path.split(output.getAbsFile())[1] == '': output.setAbsFile(output.getAbsFile()[:-1])
          # I don't think this applies anymore # if output.getFilename() == '': output.setAbsFile(output.getAbsFile()[:-1])
          #splitted_1 = (output.getPath,output.getFilename() #os.path.split(output.getAbsFile())
          #output.setAbsFile(splitted_1[1])
        #splitted = output.getAbsFile().split('.')
        #  Create csv files
        addfile = Files.returnInstance('CSV',self)
        csvfile = Files.returnInstance('CSV',self)
        addfilename = output.getBase() + '_additional_info_' + hist + '.' + output.getExt()
        csvfilename = output.getBase() + '_'                 + hist + '.' + output.getExt()
        addfile.initialize(addfilename,self.messageHandler,output.getPath(),subtype='AdditionalInfo')
        csvfile.initialize(csvfilename,self.messageHandler,output.getPath(),subtype='AdditionalInfo')
        #  Check if workingDir is present and in case join the two paths
        if self.workingDir:
          addfile.setPath(os.path.join(self.workingDir,addfile.getPath()))
          csvfile.setPath(os.path.join(self.workingDir,csvfile.getPath()))

        #  Save the data
        csvfile.open('w')
        addfile.open('w')
        #  Add history to the csv file
        np.savetxt(csvfile, HistorySet[key][0], delimiter = ",", header = utils.toString(headers))
        csvfile.write(os.linesep)
        #  process the attributes in a different csv file (different kind of informations)
        #  Add metadata to additional info csv file
        addfile.write('# History Metadata, ' + os.linesep)
        addfile.write('# ______________________________,' + '_' * len(key) + ',' + os.linesep)
        addfile.write('#number of parameters,' + os.linesep)
        addfile.write(str(attributes['nParams']) + ',' + os.linesep)
        addfile.write('#parameters,' + os.linesep)
        addfile.write(headers + os.linesep)
        addfile.write('#parentID,' + os.linesep)
        addfile.write(attributes['parentID'] + os.linesep)
        addfile.write('#start time,' + os.linesep)
        addfile.write(str(attributes['startTime']) + os.linesep)
        addfile.write('#end time,' + os.linesep)
        addfile.write(str(attributes['end_time']) + os.linesep)
        addfile.write('#number of time-steps,' + os.linesep)
        addfile.write(str(attributes['nTimeSteps']) + os.linesep)
        addfile.write(os.linesep)
    else: self.raiseAnError(NotImplementedError, 'for input type ' + self.inObj.type + ' not yet implemented.')

  def run(self, Input):  # inObj,workingDir=None):
    """
     This method executes the postprocessor action. In this case, it just returns the input
     @ In,  Input, object, object contained the data to process. (inputToInternal output)
     @ Out, object, the input
    """
    return Input[-1]
#
#
#
class BasicStatistics(BasePostProcessor):
  """
    BasicStatistics filter class. It computes all the most popular statistics
  """
  def __init__(self, messageHandler):
    """
     Constructor
     @ In, messageHandler, message handler object
    """
    BasePostProcessor.__init__(self, messageHandler)
    self.parameters = {}  # parameters dictionary (they are basically stored into a dictionary identified by tag "targets"
    self.acceptedCalcParam = ['covariance', 'NormalizedSensitivity', 'VarianceDependentSensitivity', 'sensitivity', 'pearson', 'expectedValue', 'sigma', 'variationCoefficient', 'variance', 'skewness', 'kurtosis', 'median', 'percentile']  # accepted calculation parameters
    self.what = self.acceptedCalcParam  # what needs to be computed... default...all
    self.methodsToRun = []  # if a function is present, its outcome name is here stored... if it matches one of the known outcomes, the pp is going to use the function to compute it
    self.externalFunction = []
    self.printTag = 'POSTPROCESSOR BASIC STATISTIC'
    self.requiredAssObject = (True, (['Function'], [-1]))
    self.biased = False
    self.sampled = {}
    self.calculated = {}
    
    self.comparisonVoronoi = False
    self.voronoi = False
    self.equallySpaced = False   #If the values are equally spaced, the voronoi will be done on the probability space
    self.inputsVoronoi = []
    self.outputsVoronoi = []
    self.spaceVoronoi = "input"
    self.voronoiDimensional = []
    self.proba = {}
    self.boundariesVoronoi = []   #contain the boundaries of the CrowDist if they were defined.
    self.verticesVoronoi = []
    self.sendVerticesVoronoi = False
  
  def initializeComparison(self,voronoi,parameterSet,inputs=[],outputs=[]):
    """
    Method to set up the parameters of BasicStatistics needed to be used in
    the ComparisonStatistics for the computation of the relevant stats for each 
    data to be compared.
    @ In, voronoi, Bool, if True the voronoi diagrams are going to be used to 
    compute the probability weight of each points.
    @In, parameterSet, list of the data whose stats are going to be computed.
    """
    
    self.what = ['covariance', 'NormalizedSensitivity',
     'VarianceDependentSensitivity', 'sensitivity', 'pearson',
     'expectedValue', 'sigma', 'variationCoefficient', 'variance',
     'skewness', 'kurtosis', 'median', 'percentile']
    self.proba={}
    self.externalFunction = []
    self.methodToRun = []
    self.biased = False
    self.parameters = {}
    self.voronoi=voronoi
    self.equallySpaced = False   
    self.inputsVoronoi = inputs
    self.outputsVoronoi = outputs   
    self.voronoiDimensional='unidimensional'    
    self.parameterSet = parameterSet
    self.parameters = {'targets':parameterSet}
    self.comparisonVoronoi = True 
    if len(self.parameters['targets'])==1:
      toRemove = ['VarianceDependentSensitivity','NormalizedSensitivity','covariance','pearson',] #The computation of these elements gives out some error if the ditribution is 1 dimensionnal.
      self.what = [ x for x in self.what if x not in toRemove]
  
  def returnProbaComparison(self):
    """
    Method that can return the probability weight calculated with the voronoi
    tesselation in the "run" method.
    @Out, proba, list of the probability weight of each point
    """
    
    return self.proba
  
  def inputToInternal(self, currentInp):
    """
     Method to convert an input object into the internal format that is
     understandable by this pp.
     @ In, currentInput, object, an object that needs to be converted
     @ Out, inputDict, dictionary of the converted data
    """
    
    # Each post processor knows how to handle the coming inputs. The BasicStatistics postprocessor accept all the input type (files (csv only), hdf5 and datas
    if type(currentInp) == list  : currentInput = currentInp [-1]
    else                         : currentInput = currentInp
    if type(currentInput) == dict:
      if 'targets' in currentInput.keys(): return currentInput
    inputDict = {'targets':{}, 'metadata':{}}
    if hasattr(currentInput,'type'):
      inType = currentInput.type
    else:
      if type(currentInput).__name__ == 'list'    : inType = 'list'
      else: self.raiseAnError(IOError, self, 'BasicStatistics postprocessor accepts files,HDF5,Data(s) only! Got ' + str(type(currentInput)))
    if inType not in ['HDF5', 'PointSet', 'list'] and not isinstance(inType,Files.File):
      self.raiseAnError(IOError, self, 'BasicStatistics postprocessor accepts files,HDF5,Data(s) only! Got ' + str(inType) + '!!!!')
    if isinstance(inType,Files.File):
      if currentInput.subtype == 'csv': pass
    if inType == 'HDF5': pass  # to be implemented
    if inType in ['PointSet']:
      for targetP in self.parameters['targets']:
        if   targetP in currentInput.getParaKeys('input'):
          inputDict['targets'][targetP] = currentInput.getParam('input' , targetP)
          self.sampled[targetP] = currentInput.getParam('input' , targetP)
        elif targetP in currentInput.getParaKeys('output'):
          inputDict['targets'][targetP] = currentInput.getParam('output', targetP)
          self.calculated[targetP] = currentInput.getParam('output', targetP)
      inputDict['metadata'] = currentInput.getAllMetadata()
      # now we check if the sampler that genereted the samples are from adaptive... in case... create the grid
      if 'SamplerType' in inputDict['metadata'].keys(): pass
    return inputDict

  def initialize(self, runInfo, inputs, initDict):
    """
     Method to initialize the BasicStatistic pp. In here the working dir is
     grepped.
     @ In, runInfo, dict, dictionary of run info (e.g. working dir, etc)
     @ In, inputs, list, list of inputs
     @ In, initDict, dict, dictionary with initialization options
    """
    BasePostProcessor.initialize(self, runInfo, inputs, initDict)
    self.__workingDir = runInfo['WorkingDir']

  def _localReadMoreXML(self, xmlNode):
    """
      Function to read the portion of the xml input that belongs to this specialized class
      and initialize some stuff based on the inputs got
      @ In, xmlNode    : Xml element node
      @ Out, None
    """
    for child in xmlNode:
      if child.tag == "what":
        self.what = child.text
        if self.what == 'all': self.what = self.acceptedCalcParam
        else:
          toCompute = []
          for whatc in self.what.split(','):
            toCompute.append(whatc.strip())
            if whatc not in self.acceptedCalcParam:
              if whatc.split("_")[0] != 'percentile':self.raiseAnError(IOError, 'BasicStatistics postprocessor asked unknown operation ' + whatc + '. Available ' + str(self.acceptedCalcParam))
              else:
                # check if the percentile is correct
                requestedPercentile = whatc.split("_")[-1]
                integerPercentile = utils.intConversion(requestedPercentile.replace("%",""))
                if integerPercentile is None: self.raiseAnError(IOError,"Could not convert the inputted percentile. The percentile needs to an integer between 1 and 100. Got "+requestedPercentile)
                floatPercentile = utils.floatConversion(requestedPercentile.replace("%",""))
                if floatPercentile < 1.0 or floatPercentile > 100.0: self.raiseAnError(IOError,"the percentile needs to an integer between 1 and 100. Got "+str(floatPercentile))
                if -float(integerPercentile)/floatPercentile + 1.0 > 0.0001: self.raiseAnError(IOError,"the percentile needs to an integer between 1 and 100. Got "+str(floatPercentile))
          self.what = toCompute
      if child.tag == "parameters"   : self.parameters['targets'] = child.text.split(',')
      if child.tag == "methodsToRun" : self.methodsToRun = child.text.split(',')
      if child.tag == "biased"       :
          if child.text.lower() in utils.stringsThatMeanTrue(): self.biased = True
      if child.tag == "voronoi"      :
          self.voronoi = True
          for attrib in child.attrib:
            if attrib=="inputs"      : self.inputsVoronoi = child.attrib[attrib].split(',')
            elif attrib=="outputs"   : self.outputsVoronoi = child.attrib[attrib].split(',')
            elif attrib=="space"     : self.spaceVoronoi = child.attrib[attrib].split(',')
            else                     : self.raiseAnError(IOError,"Unknown attribute " + attrib + " .Known attribute are inputs, outputs and space.")
          if child.text.lower()=="unidimensional"    : self.voronoiDimensional = "unidimensional"
          elif child.text.lower()=="multidimensional": self.voronoiDimensional = "multidimensional"
          else                                       :self.raiseAnError(IOError,"Unknown text : " + child.text.lower() + " .Expecting unidimensional or multidimensional.")     
      assert (self.parameters is not []), self.raiseAnError(IOError, 'I need parameters to work on! Please check your input for PP: ' + self.name)    
    #The computation of the elements in the "toRemove" list gives out some error if the ditribution is 1 dimensionnal.
    if len(self.parameters['targets'])==1:
      toRemove = ['VarianceDependentSensitivity','NormalizedSensitivity','covariance','pearson'] 
      self.what = [ x for x in self.what if x not in toRemove]

  def collectOutput(self, finishedjob, output):
    """
      Function to place all of the computed data into the output object
      @ In, finishedJob: A JobHandler object that is in charge of running this
                         post-processor
      @ In, output: The object where we want to place our computed results
      @ Out, None
    """
    # output
    parameterSet = list(set(list(self.parameters['targets'])))
    if finishedjob.returnEvaluation() == -1: self.raiseAnError(RuntimeError, ' No available Output to collect (Run probabably is not finished yet)')
    outputDict = finishedjob.returnEvaluation()[1]
    methodToTest = []
    for key in self.methodsToRun:
      if key not in self.acceptedCalcParam: methodToTest.append(key)
    if isinstance(output,Files.File):
      availextens = ['csv', 'txt']
      outputextension = output.getExt().lower() #split('.')[-1].lower()
      if outputextension not in availextens:
        self.raiseAWarning('BasicStatistics postprocessor output extension you input is ' + outputextension)
        self.raiseAWarning('Available are ' + str(availextens) + '. Convertint extension to ' + str(availextens[0]) + '!')
        outputextension = availextens[0]
        output.setExtension(outputextension)
      if outputextension != 'csv': separator = ' '
      else                       : separator = ','
      output.setPath(self.__workingDir)#, output.base)#output[:output.rfind('.')] + '.' + outputextension)
      self.raiseADebug('Dumping output in file named ' + output.getAbsFile())
      output.open('w')
      output.write('ComputedQuantities'+separator+separator.join(parameterSet) + os.linesep)
      quantitiesToWrite = {}
      for what in outputDict.keys():
        if what not in ['covariance', 'pearson', 'NormalizedSensitivity', 'VarianceDependentSensitivity', 'sensitivity'] + methodToTest:
          if what not in quantitiesToWrite.keys():quantitiesToWrite[what] = []
          for targetP in parameterSet:
            quantitiesToWrite[what].append('%.8E' % copy.deepcopy(outputDict[what][targetP]))
          output.write(what + separator +  separator.join(quantitiesToWrite[what])+os.linesep)
      maxLength = max(len(max(parameterSet, key = len)) + 5, 16)
      for what in outputDict.keys():
        if what in ['covariance', 'pearson', 'NormalizedSensitivity', 'VarianceDependentSensitivity']:
          self.raiseADebug('Writing parameter matrix ' + what)
          output.write(os.linesep)
          output.write(what + os.linesep)
          if outputextension != 'csv': output.write(' ' * maxLength + ''.join([str(item) + ' ' * (maxLength - len(item)) for item in parameterSet]) + os.linesep)
          else                       : output.write('matrix' + separator + ''.join([str(item) + separator for item in parameterSet]) + os.linesep)
          for index in range(len(parameterSet)):
            if outputextension != 'csv': output.write(parameterSet[index] + ' ' * (maxLength - len(parameterSet[index])) + ''.join(['%.8E' % item + ' ' * (maxLength - 14) for item in outputDict[what][index]]) + os.linesep)
            else                       : output.write(parameterSet[index] + ''.join([separator + '%.8E' % item for item in outputDict[what][index]]) + os.linesep)
        if what == 'sensitivity':
          if not self.sampled: self.raiseAWarning('No sampled Input variable defined in ' + str(self.name) + ' PP. The I/O Sensitivity Matrix wil not be calculated.')
          else:
            output.write(os.linesep)
            self.raiseADebug('Writing parameter matrix ' + what)
            output.write(what + os.linesep)
            calculatedSet = list(set(list(self.calculated)))
            sampledSet = list(set(list(self.sampled)))
            if outputextension != 'csv': output.write(' ' * maxLength + ''.join([str(item) + ' ' * (maxLength - len(item)) for item in sampledSet]) + os.linesep)
            else                       : output.write('matrix' + separator + ''.join([str(item) + separator for item in sampledSet]) + os.linesep)
            for index in range(len(calculatedSet)):
              if outputextension != 'csv': output.write(calculatedSet[index] + ' ' * (maxLength - len(calculatedSet[index])) + ''.join(['%.8E' % item + ' ' * (maxLength - 14) for item in outputDict[what][index]]) + os.linesep)
              else                       :
                output.write(calculatedSet[index] + ''.join([separator + '%.8E' % item for item in outputDict[what][index]]) + os.linesep)
      if self.externalFunction:
        self.raiseADebug('Writing External Function results')
        output.write(os.linesep + 'EXT FUNCTION ' + os.linesep)
        output.write(os.linesep)
        for what in self.methodsToRun:
          if what not in self.acceptedCalcParam:
            self.raiseADebug('Writing External Function parameter ' + what)
            output.write(what + separator + '%.8E' % outputDict[what] + os.linesep)
    elif output.type in ['PointSet','Point','History','HistorySet']:
      self.raiseADebug('Dumping output in data object named ' + output.name)
      for what in outputDict.keys():
        if what not in ['covariance', 'pearson', 'NormalizedSensitivity', 'VarianceDependentSensitivity', 'sensitivity'] + methodToTest:
          for targetP in parameterSet:
            self.raiseADebug('Dumping variable ' + targetP + '. Parameter: ' + what + '. Metadata name = ' + targetP + '-' + what)
            output.updateMetadata(targetP + '-' + what, outputDict[what][targetP])
        else:
          if what not in methodToTest:
            self.raiseADebug('Dumping matrix ' + what + '. Metadata name = ' + what + '. Targets stored in ' + 'targets-' + what)
            output.updateMetadata('targets-' + what, parameterSet)
            output.updateMetadata(what.replace("|","-"), outputDict[what])
      if self.externalFunction:
        self.raiseADebug('Dumping External Function results')
        for what in self.methodsToRun:
          if what not in self.acceptedCalcParam:
            output.updateMetadata(what, outputDict[what])
            self.raiseADebug('Dumping External Function parameter ' + what)
    elif output.type == 'HDF5' : self.raiseAWarning('Output type ' + str(output.type) + ' not yet implemented. Skip it !!!!!')
    else: self.raiseAnError(IOError, 'Output type ' + str(output.type) + ' unknown.')

  def __computeVp(self,p,weights):
    """
     Compute the sum of p-th power of weights
     @ In, p, int, the power
     @ In, weights, array-like, weights
     @ Out, sum, float, the sum of p-th power of weights
    """
    return np.sum(np.power(weights,p))

  def __computeUnbiasedCorrection(self,order,weightsOrN):
    """
     Compute unbiased correction given weights and momement order
     Reference paper:
     Lorenzo Rimoldini, "Weighted skewness and kurtosis unbiased by sample size", http://arxiv.org/pdf/1304.6564.pdf
     @ In, order, int, moment order
     @ In, weightsOrN, array-like or int, if array-like -> weights else -> number of samples
     @ Out, corrFactor, float (order <=3) or tuple of floats (order ==4), the unbiased correction factor
    """
    if order > 4: self.raiseAnError(RuntimeError,"computeUnbiasedCorrection is implemented for order <=4 only!")
    if type(weightsOrN).__name__ not in ['int','int8','int16','int64','int32']:
      if order == 2:
        V1, v1Square, V2 = self.__computeVp(1, weightsOrN), self.__computeVp(1, weightsOrN)**2.0, self.__computeVp(2, weightsOrN)
        corrFactor   = v1Square/(v1Square-V2)
      elif order == 3:
        V1, v1Cubic, V2, V3 = self.__computeVp(1, weightsOrN), self.__computeVp(1, weightsOrN)**3.0, self.__computeVp(2, weightsOrN), self.__computeVp(3, weightsOrN)
        corrFactor   =  v1Cubic/(v1Cubic-3.0*V2*V1+2.0*V3)
      elif order == 4:
        V1, v1Square, V2, V3, V4 = self.__computeVp(1, weightsOrN), self.__computeVp(1, weightsOrN)**2.0, self.__computeVp(2, weightsOrN), self.__computeVp(3, weightsOrN), self.__computeVp(4, weightsOrN)
        numer1 = v1Square*(v1Square**2.0-3.0*v1Square*V2+2.0*V1*V3+3.0*V2**2.0-3.0*V4)
        numer2 = 3.0*v1Square*(2.0*v1Square*V2-2.0*V1*V3-3.0*V2**2.0+3.0*V4)
        denom = (v1Square-V2)*(v1Square**2.0-6.0*v1Square*V2+8.0*V1*V3+3.0*V2**2.0-6.0*V4)
        corrFactor = numer1/denom ,numer2/denom
    else:
      if   order == 2: corrFactor   = float(weightsOrN)/(float(weightsOrN)-1.0)
      elif order == 3: corrFactor   = (float(weightsOrN)**2.0)/((float(weightsOrN)-1)*(float(weightsOrN)-2))
      elif order == 4: corrFactor = (float(weightsOrN)*(float(weightsOrN)**2.0-2.0*float(weightsOrN)+3.0))/((float(weightsOrN)-1)*(float(weightsOrN)-2)*(float(weightsOrN)-3)),(3.0*float(weightsOrN)*(2.0*float(weightsOrN)-3.0))/((float(weightsOrN)-1)*(float(weightsOrN)-2)*(float(weightsOrN)-3))
    return corrFactor

  def _computeKurtosis(self,arrayIn,expValue,pbWeight=None):
    """
      Method to compute the Kurtosis (fisher) of an array of observations
      @ In, arrayIn, array-like, the array of values from which the Kurtosis needs to be estimated
      @ In, expValue, float, expected value of arrayIn
      @ In, pbWeight, array-like, optional, the reliability weights that correspond to the values in 'array'. If not present, an unweighted approach is used
      @ Out, result, float, the Kurtosis of the array of data
    """
    if pbWeight is not None:
      unbiasCorr = self.__computeUnbiasedCorrection(4,pbWeight) if not self.biased else 1.0
      if not self.biased: result = -3.0 + ((1.0/self.__computeVp(1,pbWeight))*np.sum(np.dot(np.power(arrayIn - expValue,4.0),pbWeight))*unbiasCorr[0]-unbiasCorr[1]*np.power(((1.0/self.__computeVp(1,pbWeight))*np.sum(np.dot(np.power(arrayIn - expValue,2.0),pbWeight))),2.0))/np.power(self._computeVariance(arrayIn,expValue,pbWeight),2.0)
      else              : result = -3.0 + ((1.0/self.__computeVp(1,pbWeight))*np.sum(np.dot(np.power(arrayIn - expValue,4.0),pbWeight))*unbiasCorr)/np.power(self._computeVariance(arrayIn,expValue,pbWeight),2.0)
    else:
      unbiasCorr = self.__computeUnbiasedCorrection(4,len(arrayIn)) if not self.biased else 1.0
      if not self.biased: result = -3.0 + ((1.0/float(len(arrayIn)))*np.sum((arrayIn - expValue)**4)*unbiasCorr[0]-unbiasCorr[1]*(np.average((arrayIn - expValue)**2))**2.0)/(self._computeVariance(arrayIn,expValue))**2.0
      else              : result = -3.0 + ((1.0/float(len(arrayIn)))*np.sum((arrayIn - expValue)**4)*unbiasCorr)/(self._computeVariance(arrayIn,expValue))**2.0
    return result

  def _computeSkewness(self,arrayIn,expValue,pbWeight=None):
    """
      Method to compute the skewness of an array of observations
      @ In, arrayIn, array-like, the array of values from which the skewness needs to be estimated
      @ In, expValue, float, expected value of arrayIn
      @ In, pbWeight, array-like, optional, the reliability weights that correspond to the values in 'array'. If not present, an unweighted approach is used
      @ Out, result, float, the skewness of the array of data
    """
    if pbWeight is not None:
      unbiasCorr = self.__computeUnbiasedCorrection(3,pbWeight) if not self.biased else 1.0
      result = (1.0/self.__computeVp(1,pbWeight))*np.sum(np.dot(np.power(arrayIn - expValue,3.0),pbWeight))*unbiasCorr/np.power(self._computeVariance(arrayIn,expValue,pbWeight),1.5)
    else:
      unbiasCorr = self.__computeUnbiasedCorrection(3,len(arrayIn)) if not self.biased else 1.0
      result = ((1.0/float(len(arrayIn)))*np.sum((arrayIn - expValue)**3)*unbiasCorr)/np.power(self._computeVariance(arrayIn,expValue,pbWeight),1.5)
    return result

  def _computeVariance(self,arrayIn,expValue,pbWeight=None):
    """
      Method to compute the Variance (fisher) of an array of observations
      @ In, arrayIn, array-like, the array of values from which the Variance needs to be estimated
      @ In, expValue, float, expected value of arrayIn
      @ In, pbWeight, array-like, optional, the reliability weights that correspond to the values in 'array'. If not present, an unweighted approach is used
      @ Out, result, float, the Variance of the array of data
    """
    if pbWeight is not None:
      unbiasCorr = self.__computeUnbiasedCorrection(2,pbWeight) if not self.biased else 1.0
      result = (1.0/self.__computeVp(1,pbWeight))*np.average((arrayIn - expValue)**2,weights= pbWeight)*unbiasCorr
    else:
      unbiasCorr = self.__computeUnbiasedCorrection(2,len(arrayIn)) if not self.biased else 1.0
      result = np.average((arrayIn - expValue)**2)*unbiasCorr
    return result

  def _computeSigma(self,arrayIn,expValue,pbWeight=None):
    """
      Method to compute the sigma of an array of observations
      @ In, arrayIn, array-like, the array of values from which the sigma needs to be estimated
      @ In, expValue, float, expected value of arrayIn
      @ In, pbWeight, array-like, optional, the reliability weights that correspond to the values in 'array'. If not present, an unweighted approach is used
      @ Out, sigma, float, the sigma of the array of data
    """
    return np.sqrt(self._computeVariance(arrayIn,expValue,pbWeight))

  def _computeWeightedPercentile(self,arrayIn,pbWeight,percent=0.5):
    """
      Method to compute the weighted percentile in a array of data
      @ In, arrayIn, array-like, the array of values from which the percentile needs to be estimated
      @ In, pbWeight, array-like, the reliability weights that correspond to the values in 'array'
      @ In, percent, float, the percentile that needs to be computed (between 0.01 and 1.0)
      @ Out, result, float, the percentile
    """
    idxs                   = np.argsort(np.asarray(zip(pbWeight,arrayIn))[:,1])
    sortedWeightsAndPoints = np.asarray(zip(pbWeight[idxs],arrayIn[idxs]))
    weightsCDF             = np.cumsum(sortedWeightsAndPoints[:,0])
    percentileFunction     = interpolate.interp1d(weightsCDF,[i for i in range(len(arrayIn))],kind='nearest')
    try:
      index  = int(percentileFunction(percent))
      result = sortedWeightsAndPoints[index,1]
    except ValueError:
      result = np.median(arrayIn)
    return result
  
  
  def run(self, InputIn):
    """
     This method executes the postprocessor action. In this case, it computes all the requested statistical FOMs
     @ In,  InputIn, object, object contained the data to process. (inputToInternal output)
     @ Out, dictionary, Dictionary containing the results
    """
    Input = self.inputToInternal(InputIn)
    outputDict = {}
    pbWeights, pbPresent  = {'realization':None}, False
    if self.externalFunction:
      # there is an external function
      for what in self.methodsToRun:
        outputDict[what] = self.externalFunction.evaluate(what, Input['targets'])
        # check if "what" corresponds to an internal method
        if what in self.acceptedCalcParam:
          if what not in ['pearson', 'covariance', 'NormalizedSensitivity', 'VarianceDependentSensitivity', 'sensitivity']:
            if type(outputDict[what]) != dict: self.raiseAnError(IOError, 'BasicStatistics postprocessor: You have overwritten the "' + what + '" method through an external function, it must be a dictionary!!')
          else:
            if type(outputDict[what]) != np.ndarray: self.raiseAnError(IOError, 'BasicStatistics postprocessor: You have overwritten the "' + what + '" method through an external function, it must be a numpy.ndarray!!')
            if len(outputDict[what].shape) != 2:     self.raiseAnError(IOError, 'BasicStatistics postprocessor: You have overwritten the "' + what + '" method through an external function, it must be a 2D numpy.ndarray!!')
    # setting some convenience values
    parameterSet = list(set(list(self.parameters['targets'])))  # @Andrea I am using set to avoid the test: if targetP not in outputDict[what].keys()
    if self.voronoi:
      pbWeights['SampledVarsPbWeight'] = {'SampledVarsPbWeight':{}}
      if self.voronoiDimensional=='unidimensional':
        for target in parameterSet:
          if target in self.outputsVoronoi:
            if self.spaceVoronoi=='output':
              points = list(np.column_stack([Input['targets'][target]]))            
              pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][target] = np.asarray(BasicStatistics.constructVoronoi(self,points))
              self.proba[target] = pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][target]
            else:
              for inp in self.inputsVoronoi:
                if 'GridInfo' in Input['metadata'].keys(): self.equallySpaced = True    #only relevant in 1D.
                else: self.equallySpaced = True                                         #@jougcj : False if someone find a good way to define the probability weights in the value space
                if self.equallySpaced:
                  points = [[Input['metadata']['SampledVarsCdf'][i][inp]]  for i in range(len(Input['metadata']['SampledVarsCdf']))]
                else:
                  self.boundariesVoronoi = [[Input['metadata']['Boundaries'][0][inp][0],Input['metadata']['Boundaries'][0][inp][1]]]
                  points=[[Input['metadata']['SampledVars'][i][inp]] for i in range(len(Input['metadata']['SampledVars']))]            
                pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][inp] = np.asarray(BasicStatistics.constructVoronoi(self,points))
              pbW = pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][self.inputsVoronoi[0]]
              for inp in range(len(self.inputsVoronoi)-1):
                pbW=pbW*pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][self.inputsVoronoi[inp+1]]
              normal = 0
              for i in pbW:
                normal = normal + i
              pbW=pbW/normal
              pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][target] = pbW
              self.proba[target] = pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][target]
          else:   
            if 'GridInfo' in Input['metadata'].keys(): self.equallySpaced = True    #only relevant in 1D.
            else: self.equallySpaced = True                                         #@jougcj : False if someone find a good way to define the probability weights in the value space.
            if self.equallySpaced:
              points = [[Input['metadata']['SampledVarsCdf'][i][target]]  for i in range(len(Input['metadata']['SampledVarsCdf']))]
            else:
              self.boundariesVoronoi = [[Input['metadata']['Boundaries'][0][target][0],Input['metadata']['Boundaries'][0][target][1]]]
              points = list(np.column_stack([Input['targets'][target]]))
            pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][target] = np.asarray(BasicStatistics.constructVoronoi(self,points))
            self.proba[target] = pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][target]
            if any(i in ['VarianceDependentSensitivity','NormalizedSensitivity','covariance','pearson'] for i in self.what):
              if pbWeights['realization'] is None:
                if any(i in self.outputsVoronoi for i in parameterSet):
                  if 'metadata' in Input.keys(): pbPresent = 'ProbabilityWeight' in Input['metadata'].keys() if 'metadata' in Input.keys() else False
                  if not pbPresent:pbWeights['realization'] = np.asarray([1.0 / len(Input['targets'][self.parameters['targets'][0]])]*len(Input['targets'][self.parameters['targets'][0]]))
                  else:pbWeights['realization'] = Input['metadata']['ProbabilityWeight']/np.sum(Input['metadata']['ProbabilityWeight']) 
                else: 
                  points = np.column_stack([[[Input['metadata']['SampledVarsCdf'][i][target]]  for i in range(len(Input['metadata']['SampledVarsCdf']))] for target in parameterSet])
                  self.boundariesVoronoi = [[0,1]]*len(parameterSet)
                  pbWeights['realization'] = np.asarray(BasicStatistics.constructVoronoi(self,points))
      else:   
        points = list(np.column_stack([Input['targets'][x] for x in Input['targets'].keys()]))
        self.boundariesVoronoi = [[Input['metadata']['Boundaries'][0][x][0],Input['metadata']['Boundaries'][0][x][1]] for x in Input['targets'].keys()]
        pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][','.join(parameterSet)] = np.asarray(BasicStatistics.constructVoronoi(self,points))
        self.proba[','.join(parameterSet)] = pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][','.join(parameterSet)]
      pbPresent = True
      # if self.comparisonVoronoi:
      #   self.sendVerticesVoronoi = True
      #   self.verticesVoronoi = BasicStatistics.constructVoronoi(self,[[Input['targets'][parameterSet[0]][i]] for i in range(len(Input['targets'][parameterSet[0]]))])
      #   self.sendVerticesVoronoi = False
    else:
      if 'metadata' in Input.keys(): pbPresent = 'ProbabilityWeight' in Input['metadata'].keys() if 'metadata' in Input.keys() else False
      if not pbPresent:
        if 'metadata' in Input.keys():
          if 'SamplerType' in Input['metadata'].keys():
            if Input['metadata']['SamplerType'][0] != 'MC' : self.raiseAWarning('BasicStatistics postprocessor can not compute expectedValue without ProbabilityWeights. Use unit weight')
          else: self.raiseAWarning('BasicStatistics can not compute expectedValue without ProbabilityWeights. Use unit weight')
          pbWeights['realization'] = np.asarray([1.0 / len(Input['targets'][self.parameters['targets'][0]])]*len(Input['targets'][self.parameters['targets'][0]]))
      else: pbWeights['realization'] = Input['metadata']['ProbabilityWeight']/np.sum(Input['metadata']['ProbabilityWeight'])
    # This section should take the probability weight for each sampling variable
    if not self.voronoi:
      pbWeights['SampledVarsPbWeight'] = {'SampledVarsPbWeight':{}}
      if 'metadata' in Input.keys():
        for target in parameterSet:
          if 'ProbabilityWeight-'+target in Input['metadata'].keys():
            pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][target] = np.asarray(Input['metadata']['ProbabilityWeight-'+target])
            pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][target][:] = pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][target][:]/np.sum(pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][target])
    # if here because the user could have overwritten the method through the external function
    
    if 'expectedValue' not in outputDict.keys(): outputDict['expectedValue'] = {}
    expValues = np.zeros(len(parameterSet))
    for myIndex, targetP in enumerate(parameterSet):
      if pbPresent: relWeight  = pbWeights['realization'] if targetP not in pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'].keys() else pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][targetP]
      else        : relWeight  = None
      if relWeight is None: outputDict['expectedValue'][targetP] = np.mean(Input['targets'][targetP])
      else                : outputDict['expectedValue'][targetP] = np.average(Input['targets'][targetP], weights = relWeight)
      expValues[myIndex] = outputDict['expectedValue'][targetP]
    for what in self.what:
      if what not in outputDict.keys(): outputDict[what] = {}
      # sigma
      if what == 'sigma':
        for myIndex, targetP in enumerate(parameterSet):
          if pbPresent: relWeight  = pbWeights['realization'] if targetP not in pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'].keys() else pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][targetP]
          else        : relWeight  = None
          outputDict[what][targetP] = self._computeSigma(Input['targets'][targetP],expValues[myIndex],relWeight)
          if (outputDict[what][targetP] == 0):
            self.raiseAWarning('The variable: ' + targetP + ' is not dispersed (sigma = 0)! Please check your input in PP: ' + self.name)
            outputDict[what][targetP] = np.Infinity
      # variance
      if what == 'variance':
        for myIndex, targetP in enumerate(parameterSet):
          if pbPresent: relWeight  = pbWeights['realization'] if targetP not in pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'].keys() else pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][targetP]
          else        : relWeight  = None
          outputDict[what][targetP] = self._computeVariance(Input['targets'][targetP],expValues[myIndex],pbWeight=relWeight)
          if (outputDict[what][targetP] == 0):
            self.raiseAWarning('The variable: ' + targetP + ' has zero variance! Please check your input in PP: ' + self.name)
            outputDict[what][targetP] = np.Infinity
      # coefficient of variation (sigma/mu)
      if what == 'variationCoefficient':
        for myIndex, targetP in enumerate(parameterSet):
          if pbPresent: relWeight  = pbWeights['realization'] if targetP not in pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'].keys() else pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][targetP]
          else        : relWeight  = None
          sigma = self._computeSigma(Input['targets'][targetP],expValues[myIndex],relWeight)
          if (outputDict['expectedValue'][targetP] == 0):
            self.raiseAWarning('Expected Value for ' + targetP + ' is zero! Variation Coefficient can not be calculated in PP: ' + self.name)
            outputDict['expectedValue'][targetP] = np.Infinity
          outputDict[what][targetP] = sigma / outputDict['expectedValue'][targetP]
      # kurtosis
      if what == 'kurtosis':
        for myIndex, targetP in enumerate(parameterSet):
          if pbPresent: relWeight  = pbWeights['realization'] if targetP not in pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'].keys() else pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][targetP]
          else        : relWeight  = None
          outputDict[what][targetP] = self._computeKurtosis(Input['targets'][targetP],expValues[myIndex],pbWeight=relWeight)
      # skewness
      if what == 'skewness':
        for myIndex, targetP in enumerate(parameterSet):
          if pbPresent: relWeight  = pbWeights['realization'] if targetP not in pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'].keys() else pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][targetP]
          else        : relWeight  = None
          outputDict[what][targetP] = self._computeSkewness(Input['targets'][targetP],expValues[myIndex],pbWeight=relWeight)
      # median
      if what == 'median':
        if pbPresent:
          for targetP in parameterSet:
            relWeight  = pbWeights['realization'] if targetP not in pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'].keys() else pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][targetP]
            outputDict[what][targetP] = self._computeWeightedPercentile(Input['targets'][targetP],relWeight,percent=0.5)
        else:
          for targetP in parameterSet: outputDict[what][targetP] = np.median(Input['targets'][targetP])
      # percentile
      if what.split("_")[0] == 'percentile':
        outputDict.pop(what)
        if "_" not in what: whatPercentile = [what + '_5', what + '_95']
        else              : whatPercentile = [what.replace("%","")]
        for whatPerc in whatPercentile:
          if whatPerc not in outputDict.keys(): outputDict[whatPerc] = {}
          for targetP in self.parameters['targets'  ]:
            if targetP not in outputDict[whatPerc].keys() :
              if pbPresent: relWeight  = pbWeights['realization'] if targetP not in pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'].keys() else pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][targetP]
              integerPercentile             = utils.intConversion(whatPerc.split("_")[-1].replace("%",""))
              outputDict[whatPerc][targetP] = np.percentile(Input['targets'][targetP], integerPercentile) if not pbPresent else self._computeWeightedPercentile(Input['targets'][targetP],relWeight,percent=float(integerPercentile)/100.0)
      # cov matrix
      if what == 'covariance':
        feat = np.zeros((len(Input['targets'].keys()), utils.first(Input['targets'].values()).size))
        for myIndex, targetP in enumerate(parameterSet): feat[myIndex, :] = Input['targets'][targetP][:]
        outputDict[what] = self.covariance(feat, weights = pbWeights['realization'])
      # pearson matrix
      if what == 'pearson':
        feat = np.zeros((len(Input['targets'].keys()), utils.first(Input['targets'].values()).size))
        for myIndex, targetP in enumerate(parameterSet): feat[myIndex, :] = Input['targets'][targetP][:]
        outputDict[what] = self.corrCoeff(feat, weights = pbWeights['realization'])  # np.corrcoef(feat)
      # sensitivity matrix
      if what == 'sensitivity':
        if self.sampled:
          self.SupervisedEngine = {}  # dict of ROM instances (== number of targets => keys are the targets)
          for target in self.calculated:
            self.SupervisedEngine[target] = SupervisedLearning.returnInstance('SciKitLearn', self, **{'SKLtype':'linear_model|LinearRegression',
                                                                                                      'Features':','.join(self.sampled.keys()),
                                                                                                      'Target':target})
            relWeight  = pbWeights['realization'] if target not in pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'].keys() else pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][target]
            var = self._computeVariance(Input['targets'][target],expValues[parameterSet.index(target)],pbWeight=relWeight)
            if (var == 0): self.raiseAWarning('Sensitivity of a variable (' + target + ') with 0 variance is requested! in PP: ' + self.name)
            else         : self.SupervisedEngine[target].train(Input['targets'])
          for myIndex in range(len(self.calculated.keys())):
            if self.SupervisedEngine[self.calculated.keys()[myIndex]].amITrained:
              outputDict[what][myIndex] = self.SupervisedEngine[self.calculated.keys()[myIndex]].ROM.coef_
              features = self.sampled.keys()
              for index, targetP in enumerate(features):
                relWeight  = pbWeights['realization'] if targetP not in pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'].keys() else pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][targetP]
                sigma = self._computeSigma(Input['targets'][targetP],expValues[parameterSet.index(targetP)],relWeight)
                outputDict[what][myIndex][index] = outputDict[what][myIndex][index] / sigma
            else:
              value = np.zeros(len(self.calculated.keys()))
              for i in range(len(self.calculated.keys())): value[i] = np.Infinity
              outputDict[what][myIndex] = value
      # VarianceDependentSensitivity matrix
      if what == 'VarianceDependentSensitivity':
        feat = np.zeros((len(Input['targets'].keys()), utils.first(Input['targets'].values()).size))
        for myIndex, targetP in enumerate(parameterSet): feat[myIndex, :] = Input['targets'][targetP][:]
        covMatrix = self.covariance(feat, weights = pbWeights['realization'])
        variance = np.zeros(len(list(parameterSet)))
        for myIndex, targetP in enumerate(parameterSet):
          relWeight  = pbWeights['realization'] if targetP not in pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'].keys() else pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][targetP]
          variance[myIndex] = self._computeVariance(Input['targets'][targetP],expValues[myIndex],pbWeight=relWeight)
        for myIndex in range(len(parameterSet)):
          if (variance[myIndex] == 0):
             self.raiseAWarning('Variance for the parameter: ' + parameterSet[myIndex] + ' is zero!...in PP: ' + self.name)
             variance[myIndex] = np.Infinity
          outputDict[what][myIndex] = covMatrix[myIndex, :] / (variance[myIndex])
      # Normalized sensitivity matrix: linear regression slopes normalized by the mean (% change)/(% change)
      if what == 'NormalizedSensitivity':
        feat = np.zeros((len(Input['targets'].keys()), utils.first(Input['targets'].values()).size))
        for myIndex, targetP in enumerate(parameterSet): feat[myIndex, :] = Input['targets'][targetP][:]
        covMatrix = self.covariance(feat, weights = pbWeights['realization'])
        variance = np.zeros(len(list(parameterSet)))
        for myIndex, targetP in enumerate(parameterSet):
          relWeight  = pbWeights['realization'] if targetP not in pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'].keys() else pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][targetP]
          variance[myIndex] = self._computeVariance(Input['targets'][targetP],expValues[myIndex],pbWeight=relWeight)
          if (variance[myIndex] is 0):
            self.raiseAWarning('Variance for the parameter: ' + parameterSet[myIndex] + ' is zero!...in PP: ' + self.name)
            variance[myIndex] = np.Infinity
        for myIndex in range(len(parameterSet)):
          outputDict[what][myIndex] = ((covMatrix[myIndex, :] / variance) * expValues) / expValues[myIndex]
    # print on screen
    self.raiseADebug('BasicStatistics ' + str(self.name) + 'pp outputs')
    methodToTest = []
    for key in self.methodsToRun:
      if key not in self.acceptedCalcParam: methodToTest.append(key)
    msg = os.linesep
    for targetP in parameterSet:
      msg += '        *************' + '*' * len(targetP) + '***' + os.linesep
      msg += '        * Variable * ' + targetP + '  *' + os.linesep
      msg += '        *************' + '*' * len(targetP) + '***' + os.linesep
      for what in outputDict.keys():
        if what not in ['covariance', 'pearson', 'NormalizedSensitivity', 'VarianceDependentSensitivity', 'sensitivity'] + methodToTest:
          msg += '               ' + '**' + '*' * len(what) + '***' + 6 * '*' + '*' * 8 + '***' + os.linesep
          msg += '               ' + '* ' + what + ' * ' + '%.8E' % outputDict[what][targetP] + '  *' + os.linesep
          msg += '               ' + '**' + '*' * len(what) + '***' + 6 * '*' + '*' * 8 + '***' + os.linesep
    maxLength = max(len(max(parameterSet, key = len)) + 5, 16)
    if 'covariance' in outputDict.keys():
      msg += ' ' * maxLength + '*****************************' + os.linesep
      msg += ' ' * maxLength + '*         Covariance        *' + os.linesep
      msg += ' ' * maxLength + '*****************************' + os.linesep
      msg += ' ' * maxLength + ''.join([str(item) + ' ' * (maxLength - len(item)) for item in parameterSet]) + os.linesep
      for index in range(len(parameterSet)):
        msg += parameterSet[index] + ' ' * (maxLength - len(parameterSet[index])) + ''.join(['%.8E' % item + ' ' * (maxLength - 14) for item in outputDict['covariance'][index]]) + os.linesep
    if 'pearson' in outputDict.keys():
      msg += ' ' * maxLength + '*****************************' + os.linesep
      msg += ' ' * maxLength + '*    Pearson/Correlation    *' + os.linesep
      msg += ' ' * maxLength + '*****************************' + os.linesep
      msg += ' ' * maxLength + ''.join([str(item) + ' ' * (maxLength - len(item)) for item in parameterSet]) + os.linesep
      for index in range(len(parameterSet)):
        msg += parameterSet[index] + ' ' * (maxLength - len(parameterSet[index])) + ''.join(['%.8E' % item + ' ' * (maxLength - 14) for item in outputDict['pearson'][index]]) + os.linesep
    if 'VarianceDependentSensitivity' in outputDict.keys():
      msg += ' ' * maxLength + '******************************' + os.linesep
      msg += ' ' * maxLength + '*VarianceDependentSensitivity*' + os.linesep
      msg += ' ' * maxLength + '******************************' + os.linesep
      msg += ' ' * maxLength + ''.join([str(item) + ' ' * (maxLength - len(item)) for item in parameterSet]) + os.linesep
      for index in range(len(parameterSet)):
        msg += parameterSet[index] + ' ' * (maxLength - len(parameterSet[index])) + ''.join(['%.8E' % item + ' ' * (maxLength - 14) for item in outputDict['VarianceDependentSensitivity'][index]]) + os.linesep
    if 'NormalizedSensitivity' in outputDict.keys():
      msg += ' ' * maxLength + '******************************' + os.linesep
      msg += ' ' * maxLength + '* Normalized V.D.Sensitivity *' + os.linesep
      msg += ' ' * maxLength + '******************************' + os.linesep
      msg += ' ' * maxLength + ''.join([str(item) + ' ' * (maxLength - len(item)) for item in parameterSet]) + os.linesep
      for index in range(len(parameterSet)):
        msg += parameterSet[index] + ' ' * (maxLength - len(parameterSet[index])) + ''.join(['%.8E' % item + ' ' * (maxLength - 14) for item in outputDict['NormalizedSensitivity'][index]]) + os.linesep
    if 'sensitivity' in outputDict.keys():
      if not self.sampled: self.raiseAWarning('No sampled Input variable defined in ' + str(self.name) + ' PP. The I/O Sensitivity Matrix wil not be calculated.')
      else:
        msg += ' ' * maxLength + '*****************************' + os.linesep
        msg += ' ' * maxLength + '*    I/O   Sensitivity      *' + os.linesep
        msg += ' ' * maxLength + '*****************************' + os.linesep
        msg += ' ' * maxLength + ''.join([str(item) + ' ' * (maxLength - len(item)) for item in self.sampled]) + os.linesep
        sigma = {}
        for indexCalculated in range(len(self.calculated.keys())):
          #variable = self.sampled.keys()[indexSampled]
          msg += self.calculated.keys()[indexCalculated] + ' ' * (maxLength) + ''.join(['%.8E' % item + ' ' * (maxLength - 14) for item in outputDict['sensitivity'][indexCalculated]]) + os.linesep

    if self.externalFunction:
      msg += ' ' * maxLength + '+++++++++++++++++++++++++++++' + os.linesep
      msg += ' ' * maxLength + '+ OUTCOME FROM EXT FUNCTION +' + os.linesep
      msg += ' ' * maxLength + '+++++++++++++++++++++++++++++' + os.linesep
      for what in self.methodsToRun:
        if what not in self.acceptedCalcParam:
          msg += '              ' + '**' + '*' * len(what) + '***' + 6 * '*' + '*' * 8 + '***' + os.linesep
          msg += '              ' + '* ' + what + ' * ' + '%.8E' % outputDict[what] + '  *' + os.linesep
          msg += '              ' + '**' + '*' * len(what) + '***' + 6 * '*' + '*' * 8 + '***' + os.linesep
    self.raiseADebug(msg)
    return outputDict

  def covariance(self, feature, weights = None, rowvar = 1):
      """
        This method calculates the covariance Matrix for the given data.
        Unbiased unweighted covariance matrix, weights is None, bias is 0 (default)
        Biased unweighted covariance matrix,   weights is None, bias is 1
        Unbiased weighted covariance matrix,   weights is not None, bias is 0
        Biased weighted covariance matrix,     weights is not None, bias is 1
        can be calcuated depending on the selection of the inputs.
        @ In,  feature, array-like, [#targets,#samples]  features' samples
        @ In,  weights, array-like, optional, [#samples]  reliability weights. Default is None
        @ In,  rowvar, int, optional, If rowvar is non-zero, then each row represents a variable,
                                      with samples in the columns. Otherwise, the relationship is transposed. Default=1
        @ Out, covMatrix, array-like, [#targets,#targets] the covariance matrix
      """
      X = np.array(feature, ndmin = 2, dtype = np.result_type(feature, np.float64))
      diff = np.zeros(feature.shape, dtype = np.result_type(feature, np.float64))
      if weights is not None: w = np.array(weights, ndmin = 1, dtype = np.float64)
      if X.shape[0] == 1: rowvar = 1
      if rowvar:
          N = X.shape[1]
          axis = 0
      else:
          N = X.shape[0]
          axis = 1
      if weights is not None:
          sumWeights = np.sum(weights)
          sumSquareWeights = np.sum(np.square(weights))
          diff = X - np.atleast_2d(np.average(X, axis = 1 - axis, weights = weights)).T
      else:
          diff = X - np.mean(X, axis = 1 - axis, keepdims = True)
      if weights is not None:
          if not self.biased: fact = float(sumWeights / ((sumWeights * sumWeights - sumSquareWeights)))
          else:               fact = float(1.0 / (sumWeights))
      else:
          if not self.biased: fact = float(1.0 / (N - 1))
          else:               fact = float(1.0 / N)
      if fact <= 0:
          warnings.warn("Degrees of freedom <= 0", RuntimeWarning)
          fact = 0.0
      if not rowvar:
        if weights is not None: covMatrix = (np.dot(diff.T, w * diff) * fact).squeeze()
        else:                   covMatrix = (np.dot(diff.T, diff) * fact).squeeze()
      else:
        if weights is not None: covMatrix = (np.dot(w * diff, diff.T) * fact).squeeze()
        else:                   covMatrix = (np.dot(diff, diff.T) * fact).squeeze()
      return covMatrix

  def corrCoeff(self, feature, weights = None, rowvar = 1):
      """
        This method calculates the correlation coefficient Matrix (pearson) for the given data.
        Unbiased unweighted covariance matrix, weights is None, bias is 0 (default)
        Biased unweighted covariance matrix,   weights is None, bias is 1
        Unbiased weighted covariance matrix,   weights is not None, bias is 0
        Biased weighted covariance matrix,     weights is not None, bias is 1
        can be calcuated depending on the selection of the inputs.
        @ In,  feature, array-like, [#targets,#samples]  features' samples
        @ In,  weights, array-like, optional, [#samples]  reliability weights. Default is None
        @ In,  rowvar, int, optional, If rowvar is non-zero, then each row represents a variable,
                                      with samples in the columns. Otherwise, the relationship is transposed. Default=1
        @ Out, corrMatrix, array-like, [#targets,#targets] the correlation matrix
      """
      covM = self.covariance(feature, weights, rowvar)
      try:
        d = np.diag(covM)
        corrMatrix = covM / np.sqrt(np.multiply.outer(d, d))
      except ValueError:  # scalar covariance
        # nan if incorrect value (nan, inf, 0), 1 otherwise
        corrMatrix = covM / covM
      return corrMatrix
      
  def constructVoronoi(self,points):
    """
    Method used to compute the probability weight of a set of Input point by using
    the voronoi tesselation.
    @In, points, array-like, array of multidimensionnal points to be tesselated.
    @Out, proba, array-like, list of the probability weight of the different points.
    """  
    
      # Step1 : Creation of a minimal box containing the Output space, as well as a box #twice# as large to compute a larger voronoi diagram.
    boundaries=[]
    realBorder = [] # Size of the smallest box (square,cube,tesseract,etc) in which every points are contained.
    dataRange = []  # Fore each coordinate (x1,x2,x3,x4,etc) contain the minimum and the maximum of the Input Space.
    cpt = 0         # Compteur

    self.dimension = len(points[0]) # Dimension of the input space
    self.length = len(points)       # Number of points in the input space    
    
    while cpt<=self.dimension - 1:
      maxi = max(p[cpt] for p in points)
      mini = min(p[cpt] for p in points)
      dataRange.append([mini,maxi])
      realBorder.append(maxi-mini)
      cpt+=1
    largeBorder=2*max(realBorder)
    
    for i in self.boundariesVoronoi:   
      if i[1]==sys.float_info.max:del(i[1])
      if i[0]==-sys.float_info.max:del(i[0])        
    
    ##Step2 : Computation of the Voronoi diagrams
    # If the input space is one dimensionnal, the data are projected on a two dimmensionnals space so as to be able to compute the tesselation.
    # Some points are also added so as to be able to define a bounding box (else we would just have a single line)
    if self.dimension==1:
      if not self.equallySpaced:
        self.lowerBoundIndice = []
        self.upperBoundIndice = []  
        if not len(self.boundariesVoronoi[0])==2:
          distInf = -1
          distSup = -1
          if not self.boundariesVoronoi[0] or (len(self.boundariesVoronoi[0])==1 and self.boundariesVoronoi[0][0]>=max(points)):
            self.lowerBoundIndice.append(np.argmin(points))
            self.lowerBound = points[self.lowerBoundIndice[0]]
            boundaries.append(self.lowerBound[0])
            points.pop(self.lowerBoundIndice[0])
            while True:
              newIndice = np.argmin(points)
              if boundaries[0]==points[np.argmin(points)][0]:
                self.lowerBoundIndice.append(newIndice)
                points.pop(newIndice)
              else:
                break
            distInf = (min(points)[0] - boundaries[0])
          if not self.boundariesVoronoi[0] or (len(self.boundariesVoronoi[0])==1 and self.boundariesVoronoi[0][0]<=min(points)):
            self.upperBoundIndice.append(np.argmax(points))
            self.upperBound = points[self.upperBoundIndice[0]]
            boundaries.append(self.upperBound[0])
            points.pop(self.upperBoundIndice[0])
            while True:
              newIndice = np.argmax(points)
              if boundaries[-1]==points[np.argmax(points)][0]:
                self.upperBoundIndice.append(newIndice)
                points.pop(newIndice)
              else:
                break
            distSup = (boundaries[-1] - max(points)[0])
          if distInf<0: 
            boundaries.insert(0,self.boundariesVoronoi[0][0])
            distInf = 2*(min(points)[0] - self.boundariesVoronoi[0][0])
          if distSup<0: 
            boundaries.insert(1,self.boundariesVoronoi[0][0])
            distSup = 2*(min(points)[0] - self.boundariesVoronoi[0][0])
        else:
          boundaries = self.boundariesVoronoi[0]
          distInf = 2*(min(points)[0] - boundaries[0])
          distSup = 2*(boundaries[-1] - max(points)[0])
        newLateralPoints = [[min(points)[0]-distInf,0],[min(points)[0]-distInf,20],[min(points)[0]-distInf,40],
      [max(points)[0]+distSup,0],[max(points)[0]+distSup,20],[max(points)[0]+distSup,40]]
        newCoord = [20.0]*(self.length - (len(self.lowerBoundIndice)+len(self.upperBoundIndice)))
        newInfBound = [0.0] * (self.length - (len(self.lowerBoundIndice)+len(self.upperBoundIndice))) 
        newSupBound = [40.0] * (self.length - (len(self.lowerBoundIndice)+len(self.upperBoundIndice)))
      else:
        newLateralPoints = [[0,0],[0,20],[0,40],[1,0],[1,20],[1,40]]
        newCoord = [20.0]*(self.length)
        newInfBound = [0.0] * (self.length)
        newSupBound = [40.0] * (self.length) 
      boundariesDiag = np.append(np.column_stack((points,newInfBound)),np.column_stack((points,newSupBound)),axis=0)
      points2 = np.column_stack((points,newCoord))
      boundariesDiag = np.append(boundariesDiag,newLateralPoints,axis=0)
      grandeEnveloppe = boundariesDiag
      petiteEnveloppe = boundariesDiag  #Useless for the 1 dimenssionnal voronoi
      largeSetOfPoints = np.append(points2,boundariesDiag,axis=0) #Set of point in a two dimensionnal space containing the input points and the new points used to bound the input data.
      largeVoronoi = Voronoi (largeSetOfPoints)
      smallVoronoi = largeVoronoi  #Useless for the 1 dimensionnal voronoi
      defaut = True #Bool, True if the data is 1 dimmensionnal
    else:
      smallVoronoi = Voronoi(points)
      newPointsList = list(itertools.product((0,1),repeat = self.dimension)) #Creation of a list containing the vertices of a unit box
      petiteEnveloppe = np.asarray(np.multiply(newPointsList,realBorder)) #Creation of the real bounding box
      grandeEnveloppe = petiteEnveloppe*2 #Creation of the large Bounding Box, twice the size of the Real Bounding Box.
      ##Synchronisation of the two boxes with the origin of the input space  
      petiteEnveloppe+=smallVoronoi.min_bound
      grandeEnveloppe+=smallVoronoi.min_bound
      ##Modyfing the small boxes to take into account the fact that the boundaries can be given by the users.
      petiteEnveloppeDeepCopy = copy.deepcopy(petiteEnveloppe)
      for i in range(len(petiteEnveloppe)):
        for j in range(self.dimension):
          if self.boundariesVoronoi[j]:
            if petiteEnveloppe[i][j]==min([petiteEnveloppeDeepCopy[t][j] for t in range(len(petiteEnveloppe))]):
              if self.boundariesVoronoi[j][0] and self.boundariesVoronoi[j][0]<petiteEnveloppe[i][j]: petiteEnveloppe[i][j] = self.boundariesVoronoi[j][0] 
            if petiteEnveloppe[i][j]==max([petiteEnveloppeDeepCopy[t][j] for t in range(len(petiteEnveloppe))]):
              if len(self.boundariesVoronoi[j])==2 and self.boundariesVoronoi[j][1]>petiteEnveloppe[i][j]: petiteEnveloppe[i][j] = self.boundariesVoronoi[j][1]  
              elif len(self.boundariesVoronoi[j])==2 and self.boundariesVoronoi[j][0]>petiteEnveloppe[i][j]: petiteEnveloppe[i][j] = self.boundariesVoronoi[j][0]
      
      ##Centering of the big box (the small box should already be at the right position)
      grandeEnveloppe+=(0.5*(smallVoronoi.min_bound+smallVoronoi.max_bound)-smallVoronoi.max_bound)
      largeSetOfPoints = np.append(points,grandeEnveloppe,axis=0)
      largeVoronoi = Voronoi(largeSetOfPoints)
      defaut = False
      #LCVH = ConvexHull(largeSetOfPoints)

    ##Step 3 : Sorting of the cells between cells to be reduced and good-sized cells
    cells = {}  # Dictionnary whose keys are the indice of the voronoi cells that are too big, and data are the vertices of these regions.
    cells2 = {} # Dictionnary whose keys are the indice of the voronoi cells that are not too big and data are the vertices of these regions.
    for point_region in largeVoronoi.point_region:
      farAwayVertices = []
      append = False
      for vertice in largeVoronoi.regions[point_region]:
        for coordonate in range(len(largeVoronoi.vertices[vertice])):
          if largeVoronoi.vertices[vertice][coordonate]<smallVoronoi.min_bound[coordonate] or largeVoronoi.vertices[vertice][coordonate]>smallVoronoi.max_bound[coordonate]:
            farAwayVertices.append((vertice))
            append = True
            break
      if append:
        cells.setdefault(point_region,[])
        cells[point_region] = farAwayVertices
      else:
        cells2.setdefault(point_region,[])
        cells2[point_region] = largeVoronoi.regions[point_region]

    ##Step 4 : Computation of the Convex Hull of each cells, and reduction of the too-big-sized cells.
    hyperCube = ConvexHull(petiteEnveloppe) # ConvexHull of the bounding box of the Input Space
    bigConvexHull = {} # Dictionnary that will contain the convexHulls of the cells that are too big before beiing reduced
    convexHull ={} # Dictionnary whose keys are the indice of the cells and data are the ConvexHull of the vertices of the cells. 
    if self.dimension==1:
      #In 1 d, there are no cells that are too big (Because of the way new points were added)
      for indice in cells2:
        listVertices =[]      
        if all(p !=-1 for p in cells2[indice]):          
          for coord in cells2[indice]:
            convexHull.setdefault(indice,[])
            listVertices.append(largeVoronoi.vertices[coord])
          convexHull[indice] = ConvexHull(listVertices)
    
    else:        
      listHyperPlanCube = []
      c = 0
      b = 0
      d = 0
      middlePoint = (petiteEnveloppe[-1:][0] + petiteEnveloppe[0])/2
      for equation in hyperCube.equations:
        listHyperPlanCube.append(phh.Halfspace(equation[:-1],equation[-1:][0])) #List of the halfplane forming the bounding box
    
    ###Computing the ConvexHull of the right-size cells. 
      for indice in cells2:
        listVertices = []
        convexHull.setdefault(indice,[])
        for coord in cells2[indice]:
          listVertices.append(largeVoronoi.vertices[coord])    
        convexHull[indice] = ConvexHull(listVertices)
        c+=1
   
    ###Computing the ConvexHull of the cells that are too big
      for indice in cells:
        if all(p != -1 for p in largeVoronoi.regions[indice]):
        
        #Computing the ConvexHull of these Big Cells
          convexHull.setdefault(indice,[])
          bigConvexHull.setdefault(indice,[])
          listVertices =[]
          listHyperPlanCellule = []
          for coord in largeVoronoi.regions[indice]:
            listVertices.append(largeVoronoi.vertices[coord])        
        
        ##try/except : Sometimes the Qhull algorithm gives out some Qhull precision errors. When that happens the joggle option is used. 
        ##It could be a good idea to later change that by lumping together some points.
          try:
            bigConvexHull[indice] = ConvexHull(listVertices) #Computation  of the big ConvexHull
          except QhullError:
            bigConvexHull[indice] = ConvexHull(listVertices,qhull_options="QJ")
        
        #Getting halfplane equations 
          for equations in bigConvexHull[indice].equations:
            listHyperPlanCellule.append(phh.Halfspace(equations[:-1],equations[-1:][0]))
          listHyperPlan = list(listHyperPlanCube)
          listHyperPlan += listHyperPlanCellule       #Add the hyperPlan of the cells
            
            #Computing halfplanes intersections; delete reccurences, computations of new vertices
          inputPoint = [i for i,x in enumerate(largeVoronoi.point_region) if x==indice]
        #Test to take into account the fact that some of the Input points are located on the bounding box, and thus the it is not easy to compute the intersection. So we move the Input point of one eigth of the minimale distance between two points in the direction of this point. Consequently no changes should appear in the vol/aera of the ConvexHull.
          insidePoints = None
          minimum = -1
          for p in range(self.dimension):               
            if any(str(largeVoronoi.points[inputPoint][0][p]) == str(petiteEnveloppe[q][p]) for q in range(len(petiteEnveloppe))):
          #Check if one of the point is on the border    
              antecedent  = np.asarray(largeVoronoi.points[inputPoint][0]) #Coordinates of the point on the border
              listNeighbors = []              #List of neighbors.
              for ridge in largeVoronoi.ridge_points:
                if inputPoint==ridge[0]:
                  listNeighbors.append(ridge[1])
                elif inputPoint==ridge[1]:
                  listNeighbors.append(ridge[0])                  
              for point in listNeighbors:
                ptsA = np.asarray(largeVoronoi.points[point])
                dist = np.linalg.norm(antecedent-ptsA)                          
                if minimum<0 or dist<minimum:
                  minimum = dist
                  plusProche = np.asarray(largeVoronoi.points[point])
              vec = middlePoint-antecedent
              vecNorm = BasicStatistics.normalize(self,vec)
              insidePoints = antecedent + (1.0/8)*minimum*vecNorm    # Move the input point toward the middle to compute the interesection. The distance of the movement is equal to 1/8 of the distance between the point of interest and its closest nieghbors : As such, the input point is still inside his cells.
              insidePoints = insidePoints.tolist()
          if insidePoints==None:    #If the point is not on the CVH, then is good
            insidePoints = largeVoronoi.points[inputPoint][0]             
          intersect = phh.HalfspaceIntersection(listHyperPlan,insidePoints)             #Computing of the intersection
          try:
            convexHull[indice] = ConvexHull(intersect.vertices)
            d+=1
          except QhullError:
            convexHull[indice] = ConvexHull(intersect.vertices,qhull_options="QJ")
            b+=1
      print("Number of non Joggled points : ",d)
      print("Number of Joggled points : ",b)
      print("Number of good sized points : ",c)
    
    
    if self.sendVerticesVoronoi:
      self.verticesVoronoi = list(largeVoronoi.vertices)
      return self.verticesVoronoi
    
    
    ##Step 5 : Computation of probability weight from the volume of the convexHull of each cells.
    
    weight = {} 
    weightRescaled = {}
    totVol = 0
    sumWeight = 0
    proba = [0.0]*(len(points))
    boundMin = False
    boundMax = False
    if self.dimension==1:
      for p in convexHull:
        totVol+=convexHull[p].volume
    else:
      totVol = ConvexHull(petiteEnveloppe).volume  
    if self.equallySpaced:
      for p,i in enumerate(largeVoronoi.point_region):
        try:
          weight.setdefault(p+1,[])
          weight[p+1] = convexHull[i].volume/totVol  #In cas we are working on the probability space.
          sumWeight+=weight[p+1]
        except KeyError:
          weight.pop(p+1,None)
      # proba[:] = weight[:]/np.sum(weight)
      for i in range(len(points)):
        proba[i] = weight[i+1]/sumWeight
    else:  
      for p,i in enumerate(largeVoronoi.point_region):
        try:        
          weight.setdefault(p+1,[])
          weightRescaled.setdefault(p+1,[])
          # weight[p+1] = 1 - (convexHull[i].volume/totVol)  ##To give a more important weight to small cells
          weight[p+1] = totVol/convexHull[i].volume
          sumWeight+=weight[p+1]
          weightRescaled[p+1] = convexHull[i].volume
        except KeyError:        
          weight.pop(p+1,None)  
          weightRescaled.pop(p+1,None)
      weightRescaled = weightRescaled.values()
      #dicRedundance = defaultdict(list)
      
      for i in range(len(points)):
        proba[i] = weight[i+1]/sumWeight
      
      if self.dimension==1:
        if not len(self.boundariesVoronoi[0])==2:
          approxMean = np.average(points, weights = proba, axis = 0)[0]
          target = np.asarray(points)
          approxSigma = self._computeSigma(target[:,0],approxMean,proba)
        
          if not self.boundariesVoronoi[0] or (len(self.boundariesVoronoi[0])==1 and self.boundariesVoronoi[0][0]>max(points)):
            lowerBound = approxMean - 3*approxSigma          
            minVertice = min(largeVoronoi.vertices[:,0])
            volumeLowerBound = 20 * (minVertice - lowerBound)
            totVol += (volumeLowerBound)
            boundMin = True
            boundaries[0] = lowerBound
          if not self.boundariesVoronoi[0] or (len(self.boundariesVoronoi[0])==1 and self.boundariesVoronoi[0][0]<max(points)):
            upperBound = approxMean + 3*approxSigma
            maxVertice = max(largeVoronoi.vertices[:,0])
            volumeUpperBound = 20 * (upperBound - maxVertice)
            totVol += (volumeUpperBound)
            boundMax = True
            boundaries[1] = upperBound
          self.upperBoundIndice.reverse()
          self.lowerBoundIndice.reverse()
          for p in self.upperBoundIndice:
            weightRescaled.insert(p,volumeUpperBound)
            proba.insert(p,0)
          for p in self.lowerBoundIndice:
            weightRescaled.insert(p,volumeLowerBound)
            proba.insert(p,0)
          sumWeight = 0
          for p in range(len(weightRescaled)):
            # weightRescaled[p] = 1 - weightRescaled[p]/totVol
            weightRescaled[p] = totVol/weightRescaled[p]
            sumWeight+=weightRescaled[p]
          for i in range(len(weightRescaled)):
            proba[i] = weightRescaled[i]/sumWeight      
      ##Storing of the vertices (@jougcj => Useful for PP ComparisonStatistics : the vertices can be seen as the boundaries of a binning.) 
    return proba
  
    
  def normalize(self,Vector):           #Method to move in math.utils ?
    """
    Method used to normalize a given vector
    @In, array, Vector to be normalized
    @Out, array, Normalized vector 
    """
    Norm = np.linalg.norm(Vector)  
    if Norm ==0:
      return Vector
    else:
      VectorNormalisee = Vector/Norm
    return VectorNormalisee      
#
#
#
class LoadCsvIntoInternalObject(BasePostProcessor):
  """
    LoadCsvIntoInternalObject pp class. It is in charge of loading CSV files into one of the internal object (Data(s) or HDF5)
  """
  def __init__(self, messageHandler):
    """
     Constructor
     @ In, messageHandler, message handler object
    """
    BasePostProcessor.__init__(self, messageHandler)
    self.sourceDirectory = None
    self.listOfCsvFiles = []
    self.printTag = 'POSTPROCESSOR LoadCsv'

  def initialize(self, runInfo, inputs, initDict):
    """
     Method to initialize the LoadCSV pp.
     @ In, runInfo, dict, dictionary of run info (e.g. working dir, etc)
     @ In, inputs, list, list of inputs
     @ In, initDict, dict, dictionary with initialization options
    """
    BasePostProcessor.initialize(self, runInfo, inputs, initDict)
    self.__workingDir = runInfo['WorkingDir']
    if '~' in self.sourceDirectory               : self.sourceDirectory = os.path.expanduser(self.sourceDirectory)
    if not os.path.isabs(self.sourceDirectory)   : self.sourceDirectory = os.path.normpath(os.path.join(self.__workingDir, self.sourceDirectory))
    if not os.path.exists(self.sourceDirectory)  : self.raiseAnError(IOError, "The directory indicated for PostProcessor " + self.name + "does not exist. Path: " + self.sourceDirectory)
    for _dir, _, _ in os.walk(self.sourceDirectory): self.listOfCsvFiles.extend(glob(os.path.join(_dir, "*.csv")))
    if len(self.listOfCsvFiles) == 0             : self.raiseAnError(IOError, "The directory indicated for PostProcessor " + self.name + "does not contain any csv file. Path: " + self.sourceDirectory)
    self.listOfCsvFiles.sort()

  def inputToInternal(self, currentInput):
    """
     Method to convert an input object into the internal format that is
     understandable by this pp.
     @ In, currentInput, object, an object that needs to be converted
     @ Out, list, list of csv files
    """
    return self.listOfCsvFiles

  def _localReadMoreXML(self, xmlNode):
    """
      Function to read the portion of the xml input that belongs to this specialized class
      and initialize some stuff based on the inputs got
      @ In, xmlNode    : Xml element node
      @ Out, None
    """
    for child in xmlNode:
      if child.tag == "directory": self.sourceDirectory = child.text
    if not self.sourceDirectory: self.raiseAnError(IOError, "The PostProcessor " + self.name + "needs a directory for loading the csv files!")

  def collectOutput(self, finishedjob, output):
    """
      Function to place all of the computed data into the output object
      @ In, finishedJob: A JobHandler object that is in charge of running this
                         post-processor
      @ In, output: The object where we want to place our computed results
      @ Out, None
    """
    for index, csvFile in enumerate(self.listOfCsvFiles):

      attributes = {"prefix":str(index), "inputFile":self.name, "type":"csv", "name":os.path.join(self.sourceDirectory, csvFile)}
      metadata = finishedjob.returnMetadata()
      if metadata:
        for key in metadata: attributes[key] = metadata[key]
      try:                   output.addGroup(attributes, attributes)
      except AttributeError:
        outfile = Files.returnInstance('CSV',self)
        outfile.initialize(csvFile,self.messageHandler,path=self.sourceDirectory)
        output.addOutput(outfile, attributes)
        if metadata:
          for key, value in metadata.items(): output.updateMetadata(key, value, attributes)

  def run(self, InputIn):
    """
     This method executes the postprocessor action. In this case, it just returns the list of csv files
     @ In,  Input, object, object contained the data to process. (inputToInternal output)
     @ Out, list, list of csv files
    """
    return self.listOfCsvFiles
#
#
#
class LimitSurface(BasePostProcessor):
  """
    LimitSurface filter class. It computes the limit surface associated to a dataset
  """

  def __init__(self, messageHandler):
    """
     Constructor
     @ In, messageHandler, message handler object
    """
    BasePostProcessor.__init__(self,messageHandler)
    self.parameters        = {}               #parameters dictionary (they are basically stored into a dictionary identified by tag "targets"
    self.surfPoint         = None             #coordinate of the points considered on the limit surface
    self.testMatrix        = OrderedDict()    #This is the n-dimensional matrix representing the testing grid
    self.gridCoord         = {}               #Grid coordinates
    self.functionValue     = {}               #This a dictionary that contains np vectors with the value for each variable and for the goal function
    self.ROM               = None             #Pointer to a ROM
    self.externalFunction  = None             #Pointer to an external Function
    self.tolerance         = 1.0e-4           #SubGrid tollerance
    self.gridFromOutside   = False            #The grid has been passed from outside (self._initFromDict)?
    self.lsSide            = "negative"       # Limit surface side to compute the LS for (negative,positive,both)
    self.gridEntity        = None
    self.bounds            = None
    self.jobHandler        = None
    self.transfMethods     = {}
    self.requiredAssObject = (True,(['ROM','Function'],[-1,1]))
    self.printTag = 'POSTPROCESSOR LIMITSURFACE'

  def _localWhatDoINeed(self):
    """
    This method is a local mirror of the general whatDoINeed method.
    It is implemented by the samplers that need to request special objects
    @ In , None, None
    @ Out, needDict, list of objects needed
    """
    return {'internal':[(None,'jobHandler')]}

  def _localGenerateAssembler(self,initDict):
    """
    Generates the assembler.
    @ In, initDict, dict of init objects
    @ Out, None
    """
    self.jobHandler = initDict['internal']['jobHandler']

  def inputToInternal(self, currentInp):
    """
     Method to convert an input object into the internal format that is
     understandable by this pp.
     @ In, currentInput, object, an object that needs to be converted
     @ Out, dict, the resulting dictionary containing features and response
    """
    # each post processor knows how to handle the coming inputs. The BasicStatistics postprocessor accept all the input type (files (csv only), hdf5 and datas
    if type(currentInp) == list: currentInput = currentInp[-1]
    else                       : currentInput = currentInp
    if type(currentInp) == dict:
      if 'targets' in currentInput.keys(): return
    inputDict = {'targets':{}, 'metadata':{}}
    #FIXME I don't think this is checking for files, HDF5 and dataobjects
    if hasattr(currentInput,'type'):
      inType = currentInput.type
    else:
      self.raiseAnError(IOError, self, 'LimitSurface postprocessor accepts files,HDF5,Data(s) only! Got ' + str(type(currentInput)))
    if isinstance(currentInp,Files.File):
      if currentInput.subtype == 'csv': pass
      #FIXME else?  This seems like hollow code right now.
    if inType == 'HDF5': pass  # to be implemented
    if inType in ['PointSet']:
      for targetP in self.parameters['targets']:
        if   targetP in currentInput.getParaKeys('input'): inputDict['targets'][targetP] = currentInput.getParam('input' , targetP)
        elif targetP in currentInput.getParaKeys('output'): inputDict['targets'][targetP] = currentInput.getParam('output', targetP)
      inputDict['metadata'] = currentInput.getAllMetadata()
    # to be added
    return inputDict

  def _initializeLSpp(self, runInfo, inputs, initDict):
    """
     Method to initialize the LS post processor (create grid, etc.)
     @ In, runInfo, dict, dictionary of run info (e.g. working dir, etc)
     @ In, inputs, list, list of inputs
     @ In, initDict, dict, dictionary with initialization options
    """
    BasePostProcessor.initialize(self, runInfo, inputs, initDict)
    self.gridEntity = GridEntities.returnInstance("MultiGridEntity",self,self.messageHandler)
    self.__workingDir     = runInfo['WorkingDir']
    self.externalFunction = self.assemblerDict['Function'][0][3]
    if 'ROM' not in self.assemblerDict.keys():
      self.ROM = SupervisedLearning.returnInstance('SciKitLearn', self, **{'SKLtype':'neighbors|KNeighborsClassifier',"n_neighbors":1, 'Features':','.join(list(self.parameters['targets'])), 'Target':self.externalFunction.name})
    else: self.ROM = self.assemblerDict['ROM'][0][3]
    self.ROM.reset()
    self.indexes = -1
    for index, inp in enumerate(self.inputs):
      if type(inp).__name__ in ['str', 'bytes', 'unicode']: self.raiseAnError(IOError, 'LimitSurface PostProcessor only accepts Data(s) as inputs!')
      if inp.type in ['PointSet', 'Point']: self.indexes = index
    if self.indexes == -1: self.raiseAnError(IOError, 'LimitSurface PostProcessor needs a Point or PointSet as INPUT!!!!!!')
    else:
      # check if parameters are contained in the data
      inpKeys = self.inputs[self.indexes].getParaKeys("inputs")
      outKeys = self.inputs[self.indexes].getParaKeys("outputs")
      self.paramType = {}
      for param in self.parameters['targets']:
        if param not in inpKeys + outKeys: self.raiseAnError(IOError, 'LimitSurface PostProcessor: The param ' + param + ' not contained in Data ' + self.inputs[self.indexes].name + ' !')
        if param in inpKeys: self.paramType[param] = 'inputs'
        else:                self.paramType[param] = 'outputs'
    if self.bounds == None:
      self.bounds = {"lowerBounds":{},"upperBounds":{}}
      for key in self.parameters['targets']: self.bounds["lowerBounds"][key], self.bounds["upperBounds"][key] = min(self.inputs[self.indexes].getParam(self.paramType[key],key,nodeid = 'RecontructEnding')), max(self.inputs[self.indexes].getParam(self.paramType[key],key,nodeid = 'RecontructEnding'))
    self.gridEntity.initialize(initDictionary={"rootName":self.name,'constructTensor':True, "computeCells":initDict['computeCells'] if 'computeCells' in initDict.keys() else False,
                                               "dimensionNames":self.parameters['targets'], "lowerBounds":self.bounds["lowerBounds"],"upperBounds":self.bounds["upperBounds"],
                                               "volumetricRatio":self.tolerance   ,"transformationMethods":self.transfMethods})
    self.nVar                  = len(self.parameters['targets'])                                  # Total number of variables
    self.axisName              = self.gridEntity.returnParameter("dimensionNames",self.name)      # this list is the implicit mapping of the name of the variable with the grid axis ordering self.axisName[i] = name i-th coordinate
    self.testMatrix[self.name] = np.zeros(self.gridEntity.returnParameter("gridShape",self.name)) # grid where the values of the goalfunction are stored

  def _initializeLSppROM(self, inp, raiseErrorIfNotFound = True):
    """
     Method to initialize the LS accelleration rom
     @ In, inp, Data(s) object, data object containing the training set
     @ In, raiseErrorIfNotFound, bool, throw an error if the limit surface is not found
    """
    self.raiseADebug('Initiate training')
    if type(inp) == dict:
      self.functionValue.update(inp['inputs' ])
      self.functionValue.update(inp['outputs'])
    else:
      self.functionValue.update(inp.getParametersValues('inputs', nodeid = 'RecontructEnding'))
      self.functionValue.update(inp.getParametersValues('outputs', nodeid = 'RecontructEnding'))
    # recovery the index of the last function evaluation performed
    if self.externalFunction.name in self.functionValue.keys(): indexLast = len(self.functionValue[self.externalFunction.name]) - 1
    else                                                      : indexLast = -1
    # index of last set of point tested and ready to perform the function evaluation
    indexEnd = len(self.functionValue[self.axisName[0]]) - 1
    tempDict = {}
    if self.externalFunction.name in self.functionValue.keys():
      self.functionValue[self.externalFunction.name] = np.append(self.functionValue[self.externalFunction.name], np.zeros(indexEnd - indexLast))
    else: self.functionValue[self.externalFunction.name] = np.zeros(indexEnd + 1)

    for myIndex in range(indexLast + 1, indexEnd + 1):
      for key, value in self.functionValue.items(): tempDict[key] = value[myIndex]
      self.functionValue[self.externalFunction.name][myIndex] = self.externalFunction.evaluate('residuumSign', tempDict)
      if abs(self.functionValue[self.externalFunction.name][myIndex]) != 1.0: self.raiseAnError(IOError, 'LimitSurface: the function evaluation of the residuumSign method needs to return a 1 or -1!')
      if type(inp) != dict:
        if self.externalFunction.name in inp.getParaKeys('inputs'): inp.self.updateInputValue (self.externalFunction.name, self.functionValue[self.externalFunction.name][myIndex])
        if self.externalFunction.name in inp.getParaKeys('output'): inp.self.updateOutputValue(self.externalFunction.name, self.functionValue[self.externalFunction.name][myIndex])
      else:
        if self.externalFunction.name in inp['inputs' ].keys(): inp['inputs' ][self.externalFunction.name] = np.concatenate((inp['inputs'][self.externalFunction.name],np.asarray(self.functionValue[self.externalFunction.name][myIndex])))
        if self.externalFunction.name in inp['outputs'].keys(): inp['outputs'][self.externalFunction.name] = np.concatenate((inp['outputs'][self.externalFunction.name],np.asarray(self.functionValue[self.externalFunction.name][myIndex])))
    if np.sum(self.functionValue[self.externalFunction.name]) == float(len(self.functionValue[self.externalFunction.name])) or np.sum(self.functionValue[self.externalFunction.name]) == -float(len(self.functionValue[self.externalFunction.name])):
      if raiseErrorIfNotFound: self.raiseAnError(ValueError, 'LimitSurface: all the Function evaluations brought to the same result (No Limit Surface has been crossed...). Increase or change the data set!')
      else                   : self.raiseAWarning('LimitSurface: all the Function evaluations brought to the same result (No Limit Surface has been crossed...)!')
    #printing----------------------
    self.raiseADebug('LimitSurface: Mapping of the goal function evaluation performed')
    self.raiseADebug('LimitSurface: Already evaluated points and function values:')
    keyList = list(self.functionValue.keys())
    self.raiseADebug(','.join(keyList))
    for index in range(indexEnd + 1):
      self.raiseADebug(','.join([str(self.functionValue[key][index]) for key in keyList]))
    #printing----------------------
    tempDict = {}
    for name in self.axisName: tempDict[name] = np.asarray(self.functionValue[name])
    tempDict[self.externalFunction.name] = self.functionValue[self.externalFunction.name]
    self.ROM.train(tempDict)
    self.raiseADebug('LimitSurface: Training performed')
    self.raiseADebug('LimitSurface: Training finished')

  def initialize(self, runInfo, inputs, initDict):
    """
     Method to initialize the LS pp.
     @ In, runInfo, dict, dictionary of run info (e.g. working dir, etc)
     @ In, inputs, list, list of inputs
     @ In, initDict, dict, dictionary with initialization options
    """
    self._initializeLSpp(runInfo, inputs, initDict)
    self._initializeLSppROM(self.inputs[self.indexes])

  def _initFromDict(self, dictIn):
    """
      Initialize the LS pp from a dictionary (not from xml input).
      This is used when other objects initialize and use the LS pp for internal
      calculations
      @ In, dictIn, dict, dictionary of initialization options
    """
    if "parameters" not in dictIn.keys()             : self.raiseAnError(IOError, 'No Parameters specified in "dictIn" dictionary !!!!')
    if "name"                  in dictIn.keys()      : self.name          = dictIn["name"]
    if type(dictIn["parameters"]).__name__ == "list" : self.parameters['targets'] = dictIn["parameters"]
    else                                             : self.parameters['targets'] = dictIn["parameters"].split(",")
    if "bounds"                in dictIn.keys()      : self.bounds        = dictIn["bounds"]
    if "transformationMethods" in dictIn.keys()      : self.transfMethods = dictIn["transformationMethods"]
    if "verbosity"             in dictIn.keys()      : self.verbosity     = dictIn['verbosity']
    if "side"                  in dictIn.keys()      : self.lsSide        = dictIn["side"]
    if "tolerance"             in dictIn.keys()      : self.tolerance     = float(dictIn["tolerance"])
    if self.lsSide not in ["negative", "positive", "both"]: self.raiseAnError(IOError, 'Computation side can be positive, negative, both only !!!!')

  def getFunctionValue(self):
    """
    Method to get a pointer to the dictionary self.functionValue
    @ In, None
    @ Out, dictionary, self.functionValue
    """
    return self.functionValue

  def getTestMatrix(self, nodeName=None,exceptionGrid=None):
    """
    Method to get a pointer to the testMatrix object (evaluation grid)
    @ In, nodeName, string, optional, which grid node should be returned. If None, the self.name one, If "all", all of theme, else the nodeName
    @ In, exceptionGrid, string, optional, which grid node should should not returned in case nodeName is "all"
    @ Out, ndarray , self.testMatrix
    """
    if nodeName == None  : return self.testMatrix[self.name]
    elif nodeName =="all":
      if exceptionGrid == None: return self.testMatrix
      else:
        returnDict = OrderedDict()
        wantedKeys = list(self.testMatrix.keys())
        wantedKeys.pop(wantedKeys.index(exceptionGrid))
        for key in wantedKeys: returnDict[key] = self.testMatrix[key]
        return returnDict
    else                 : return self.testMatrix[nodeName]

  def _localReadMoreXML(self, xmlNode):
    """
      Function to read the portion of the xml input that belongs to this specialized class
      and initialize some stuff based on the inputs got
      @ In, xmlNode    : Xml element node
      @ Out, None
    """
    initDict = {}
    for child in xmlNode: initDict[child.tag] = child.text
    initDict.update(xmlNode.attrib)
    self._initFromDict(initDict)

  def collectOutput(self, finishedjob, output):
    """
      Function to place all of the computed data into the output object
      @ In, finishedJob: A JobHandler object that is in charge of running this
                         post-processor
      @ In, output: The object where we want to place our computed results
      @ Out, None
    """
    if finishedjob.returnEvaluation() == -1: self.raiseAnError(RuntimeError, 'No available Output to collect (Run probabably is not finished yet)')
    self.raiseADebug(str(finishedjob.returnEvaluation()))
    limitSurf = finishedjob.returnEvaluation()[1]
    if limitSurf[0] is not None:
      for varName in output.getParaKeys('inputs'):
        for varIndex in range(len(self.axisName)):
          if varName == self.axisName[varIndex]:
            output.removeInputValue(varName)
            for value in limitSurf[0][:, varIndex]: output.updateInputValue(varName, copy.copy(value))
      output.removeOutputValue(self.externalFunction.name)
      for value in limitSurf[1]: output.updateOutputValue(self.externalFunction.name, copy.copy(value))

  def refineGrid(self,refinementSteps=2):
    """
     Method to refine the internal grid based on the limit surface previously computed
     @ In, refinementSteps, int, number of refinement steps
     @ Out, None
    """
    cellIds = self.gridEntity.retrieveCellIds([self.listsurfPointNegative,self.listsurfPointPositive],self.name)
    if self.getLocalVerbosity() == 'debug': self.raiseADebug("Limit Surface cell IDs are: \n"+ " \n".join([str(cellID) for cellID in cellIds]))
    self.raiseAMessage("Number of cells to be refined are "+str(len(cellIds))+". RefinementSteps = "+str(max([refinementSteps,2]))+"!")
    self.gridEntity.refineGrid({"cellIDs":cellIds,"refiningNumSteps":int(max([refinementSteps,2]))})
    for nodeName in self.gridEntity.getAllNodesNames(self.name):
      if nodeName != self.name: self.testMatrix[nodeName] = np.zeros(self.gridEntity.returnParameter("gridShape",nodeName))

  def run(self, InputIn = None, returnListSurfCoord = False, exceptionGrid = None, merge = True):
    """
     This method executes the postprocessor action. In this case it computes the limit surface.
     @ In ,InputIn, dictionary, dictionary of data to process
     @ In ,returnListSurfCoord, boolean, True if listSurfaceCoordinate needs to be returned
     @ Out, dictionary, Dictionary containing the limitsurface
    """
    allGridNames = self.gridEntity.getAllNodesNames(self.name)
    if exceptionGrid != None:
      try   : allGridNames.pop(allGridNames.index(exceptionGrid))
      except: pass
    self.surfPoint, evaluations, listsurfPoint = OrderedDict().fromkeys(allGridNames), OrderedDict().fromkeys(allGridNames) ,OrderedDict().fromkeys(allGridNames)
    for nodeName in allGridNames:
      #if skipMainGrid == True and nodeName == self.name: continue
      self.testMatrix[nodeName] = np.zeros(self.gridEntity.returnParameter("gridShape",nodeName))
      self.gridCoord[nodeName] = self.gridEntity.returnGridAsArrayOfCoordinates(nodeName=nodeName)
      tempDict ={}
      for  varId, varName in enumerate(self.axisName): tempDict[varName] = self.gridCoord[nodeName][:,varId]
      self.testMatrix[nodeName].shape     = (self.gridCoord[nodeName].shape[0])                       #rearrange the grid matrix such as is an array of values
      self.testMatrix[nodeName][:]        = self.ROM.evaluate(tempDict)                               #get the prediction on the testing grid
      self.testMatrix[nodeName].shape     = self.gridEntity.returnParameter("gridShape",nodeName)     #bring back the grid structure
      self.gridCoord[nodeName].shape      = self.gridEntity.returnParameter("gridCoorShape",nodeName) #bring back the grid structure
      self.raiseADebug('LimitSurface: Prediction performed')
      # here next the points that are close to any change are detected by a gradient (it is a pre-screener)
      toBeTested = np.squeeze(np.dstack(np.nonzero(np.sum(np.abs(np.gradient(self.testMatrix[nodeName])), axis = 0))))
      #printing----------------------
      self.raiseADebug('LimitSurface:  Limit surface candidate points')
      if self.getLocalVerbosity() == 'debug':
        for coordinate in np.rollaxis(toBeTested, 0):
          myStr = ''
          for iVar, varnName in enumerate(self.axisName): myStr += varnName + ': ' + str(coordinate[iVar]) + '      '
          self.raiseADebug('LimitSurface: ' + myStr + '  value: ' + str(self.testMatrix[nodeName][tuple(coordinate)]))
      # printing----------------------
      # check which one of the preselected points is really on the limit surface
      nNegPoints, nPosPoints                       =  0, 0
      listsurfPointNegative, listsurfPointPositive = [], []

      if self.lsSide in ["negative", "both"]:
        # it returns the list of points belonging to the limit state surface and resulting in a negative response by the ROM
        listsurfPointNegative = self.__localLimitStateSearch__(toBeTested, -1, nodeName)
        nNegPoints = len(listsurfPointNegative)
      if self.lsSide in ["positive", "both"]:
        # it returns the list of points belonging to the limit state surface and resulting in a positive response by the ROM
        listsurfPointPositive = self.__localLimitStateSearch__(toBeTested, 1, nodeName)
        nPosPoints = len(listsurfPointPositive)
      listsurfPoint[nodeName] = listsurfPointNegative + listsurfPointPositive
      #printing----------------------
      if self.getLocalVerbosity() == 'debug':
        if len(listsurfPoint[nodeName]) > 0: self.raiseADebug('LimitSurface: Limit surface points:')
        for coordinate in listsurfPoint[nodeName]:
          myStr = ''
          for iVar, varnName in enumerate(self.axisName): myStr += varnName + ': ' + str(coordinate[iVar]) + '      '
          self.raiseADebug('LimitSurface: ' + myStr + '  value: ' + str(self.testMatrix[nodeName][tuple(coordinate)]))
      # if the number of point on the limit surface is > than zero than save it
      if len(listsurfPoint[nodeName]) > 0:
        self.surfPoint[nodeName] = np.ndarray((len(listsurfPoint[nodeName]), self.nVar))
        evaluations[nodeName] = np.concatenate((-np.ones(nNegPoints), np.ones(nPosPoints)), axis = 0)
        for pointID, coordinate in enumerate(listsurfPoint[nodeName]):
          self.surfPoint[nodeName][pointID, :] = self.gridCoord[nodeName][tuple(coordinate)]
    if self.name != exceptionGrid: self.listsurfPointNegative, self.listsurfPointPositive = listsurfPoint[self.name][:nNegPoints-1],listsurfPoint[self.name][nNegPoints:]
    if merge == True:
      evals = np.hstack(evaluations.values())
      listsurfPoints = np.hstack(listsurfPoint.values())
      surfPoint = np.hstack(self.surfPoint.values())
      if returnListSurfCoord: return surfPoint, evals, listsurfPoints
      else                  : return surfPoint, evals
    else:
      if returnListSurfCoord: return self.surfPoint, evaluations, listsurfPoint
      else                  : return self.surfPoint, evaluations


  def __localLimitStateSearch__(self, toBeTested, sign, nodeName):
    """
    It returns the list of points belonging to the limit state surface and resulting in
    positive or negative responses by the ROM, depending on whether ''sign''
    equals either -1 or 1, respectively.
    """
    listsurfPoint = []
    gridShape = self.gridEntity.returnParameter("gridShape",nodeName)
    myIdList = np.zeros(self.nVar,dtype=int)
    putIt = np.zeros(self.nVar,dtype=bool)
    for coordinate in np.rollaxis(toBeTested, 0):
      myIdList[:] = coordinate
      putIt[:]    = False
      if self.testMatrix[nodeName][tuple(coordinate)] * sign > 0:
        for iVar in range(self.nVar):
          if coordinate[iVar] + 1 < gridShape[iVar]:
            myIdList[iVar] += 1
            if self.testMatrix[nodeName][tuple(myIdList)] * sign <= 0:
              putIt[iVar] = True
              listsurfPoint.append(copy.copy(coordinate))
              break
            myIdList[iVar] -= 1
            if coordinate[iVar] > 0:
              myIdList[iVar] -= 1
              if self.testMatrix[nodeName][tuple(myIdList)] * sign <= 0:
                putIt[iVar] = True
                listsurfPoint.append(copy.copy(coordinate))
                break
              myIdList[iVar] += 1
      #if len(set(putIt)) == 1 and  list(set(putIt))[0] == True: listsurfPoint.append(copy.copy(coordinate))
    return listsurfPoint
#
#
#

class ExternalPostProcessor(BasePostProcessor):
  """
    ExternalPostProcessor class. It will apply an arbitrary python function to
    a dataset and append each specified function's output to the output data
    object, thus the function should produce a scalar value per row of data. I
    have no idea what happens if the function produces multiple outputs.
  """
  def __init__(self, messageHandler):
    """
     Constructor
     @ In, messageHandler, message handler object
    """
    BasePostProcessor.__init__(self, messageHandler)
    self.methodsToRun = []  # A list of strings specifying what
                                        # methods the user wants to compute from
                                        # the external interfaces

    self.externalInterfaces = []  # A list of Function objects that
                                        # hopefully contain definitions for all
                                        # of the methods the user wants

    self.printTag = 'POSTPROCESSOR EXTERNAL FUNCTION'
    self.requiredAssObject = (True, (['Function'], ['n']))

  def inputToInternal(self, currentInp):
    """
      Function to convert the received input into a format this object can
      understand
      @ In, currentInp: Some form of data object or list of data objects handed
                        to the post-processor
      @ Out, An input dictionary this object can process
    """

    if type(currentInp) == dict:
      if 'targets' in currentInp.keys(): return
    currentInput = currentInp
    if type(currentInput) != list: currentInput = [currentInput]
    inputDict = {'targets':{}, 'metadata':{}}
    metadata = []
    for item in currentInput:
      inType = None
      if hasattr(item, 'type')  : inType = item.type
      elif type(item) in [list]: inType = "list"
      if inType not in ['HDF5', 'PointSet', 'list'] and not isinstance(item,Files.File):
        self.raiseAWarning(self, 'Input type ' + type(item).__name__ + ' not' + ' recognized. I am going to skip it.')
      elif isinstance(item,Files.File):
        if currentInput.subtype == 'csv': self.raiseAWarning(self, 'Input type ' + inType + ' not yet ' + 'implemented. I am going to skip it.')
      elif inType == 'HDF5':
        # TODO
          self.raiseAWarning(self, 'Input type ' + inType + ' not yet ' + 'implemented. I am going to skip it.')
      elif inType == 'PointSet':
        for param in item.getParaKeys('input') : inputDict['targets'][param] = item.getParam('input', param)
        for param in item.getParaKeys('output'): inputDict['targets'][param] = item.getParam('output', param)
        metadata.append(item.getAllMetadata())
      # Not sure if we need it, but keep a copy of every inputs metadata
      inputDict['metadata'] = metadata

    if len(inputDict['targets'].keys()) == 0: self.raiseAnError(IOError, "No input variables have been found in the input objects!")
    for interface in self.externalInterfaces:
      for _ in self.methodsToRun:
        # The function should reference self and use the same variable names
        # as the xml file
        for param in interface.parameterNames():
          if param not in inputDict['targets']:
            self.raiseAnError(IOError, self, 'variable \"' + param + '\" unknown.' + ' Please verify your external' + ' script (' + interface.functionFile
                                          + ') variables match the data'
                                          + ' available in your dataset.')
    return inputDict

  def initialize(self, runInfo, inputs, initDict):
    """
     Method to initialize the External pp.
     @ In, runInfo, dict, dictionary of run info (e.g. working dir, etc)
     @ In, inputs, list, list of inputs
     @ In, initDict, dict, dictionary with initialization options
    """
    BasePostProcessor.initialize(self, runInfo, inputs, initDict)
    self.__workingDir = runInfo['WorkingDir']
    for key in self.assemblerDict.keys():
      if 'Function' in key:
        indice = 0
        for _ in self.assemblerDict[key]:
          self.externalInterfaces.append(self.assemblerDict[key][indice][3])
          indice += 1

  def _localReadMoreXML(self, xmlNode):
    """
      Function to grab the names of the methods this post-processor will be
      using
      @ In, xmlNode    : Xml element node
      @ Out, None
    """
    for child in xmlNode:
      if child.tag == 'method':
        methods = child.text.split(',')
        self.methodsToRun.extend(methods)

  def collectOutput(self, finishedJob, output):
    """
      Function to place all of the computed data into the output object
      @ In, finishedJob: A JobHandler object that is in charge of running this
                         post-processor
      @ In, output: The object where we want to place our computed results
      @ Out, None
    """
    if finishedJob.returnEvaluation() == -1:
      # #TODO This does not feel right
      self.raiseAnError(RuntimeError, 'No available Output to collect (Run '
                                       + 'probably did not finish yet)')
    inputList = finishedJob.returnEvaluation()[0]
    outputDict = finishedJob.returnEvaluation()[1]

    if isinstance(output,Files.File):
      self.raiseAWarning('Output type File not'
                               + ' yet implemented. I am going to skip it.')
    elif output.type == 'DataObjects':
      self.raiseAWarning('Output type ' + type(output).__name__ + ' not'
                               + ' yet implemented. I am going to skip it.')
    elif output.type == 'HDF5':
      self.raiseAWarning('Output type ' + type(output).__name__ + ' not'
                               + ' yet implemented. I am going to skip it.')
    elif output.type == 'PointSet':
      requestedInput = output.getParaKeys('input')
      requestedOutput = output.getParaKeys('output')
      # # The user can simply ask for a computation that may exist in multiple
      # # interfaces, in that case, we will need to qualify their names for the
      # # output. The names should already be qualified from the outputDict.
      # # However, the user may have already qualified the name, so make sure and
      # # test whether the unqualified name exists in the requestedOutput before
      # # replacing it.
      for key, replacements in outputDict['qualifiedNames'].iteritems():
        if key in requestedOutput:
          requestedOutput.remove(key)
          requestedOutput.extend(replacements)

      # # Grab all data from the outputDict and anything else requested not
      # # present in the outputDict will be copied from the input data.
      # # TODO: User may want to specify which dataset the parameter comes from.
      # #       For now, we assume that if we find more than one an error will
      # #      occur.
      # # FIXME: There is an issue that the data size should be determined before
      # #        entering this loop, otherwise if say a scalar is first added,
      # #        then dataLength will be 1 and everything longer will be placed
      # #        in the Metadata.
      # #        How do we know what size the output data should be?
      dataLength = None
      for key in requestedInput + requestedOutput:
        storeInOutput = True
        value = []
        if key in outputDict:
          value = outputDict[key]
        else:
          foundCount = 0
          if key in requestedInput:
            for inputData in inputList:
              if key in inputData.getParametersValues('input').keys():
                value = inputData.getParametersValues('input')[key]
                foundCount += 1
          else:
            for inputData in inputList:
                if key in inputData.getParametersValues('output').keys():
                  value = inputData.getParametersValues('output')[key]
                  foundCount += 1

          if foundCount == 0:
            self.raiseAnError(IOError, key + ' not found in the input '
                                            + 'object or the computed output '
                                            + 'object.')
          elif foundCount > 1:
            self.raiseAnError(IOError, key + ' is ambiguous since it occurs'
                                            + ' in multiple input objects.')

        # # We need the size to ensure the data size is consistent, but there
        # # is no guarantee the data is not scalar, so this check is necessary
        myLength = 1
        if not hasattr(value, "__iter__"):
          value = [value]
        myLength = len(value)

        if dataLength is None:
          dataLength = myLength
        elif dataLength != myLength:
          self.raiseAWarning('Requested output for ' + key + ' has a'
                                    + ' non-conformant data size ('
                                    + str(dataLength) + ' vs ' + str(myLength)
                                    + '), it is being placed in the metadata.')
          storeInOutput = False

        # # Finally, no matter what, place the requested data somewhere
        # # accessible
        if storeInOutput:
          if key in requestedInput:
            for val in value:
              output.updateInputValue(key, val)
          else:
            for val in value:
              output.updateOutputValue(key, val)
        else:
          if not hasattr(value, "__iter__"):
            value = [value]
          for val in value:
            output.updateMetadata(key, val)

    else: self.raiseAnError(IOError, 'Unknown output type: ' + str(output.type))

  def run(self, InputIn):
    """
     This method executes the postprocessor action. In this case it performs the action defined int
     the external pp
     @ In , InputIn, dictionary, dictionary of data to process
     @ Out, dictionary, Dictionary containing the post-processed results
    """
    Input = self.inputToInternal(InputIn)
    outputDict = {'qualifiedNames' : {}}
    # # This will map the name to its appropriate interface and method
    # # in the case of a function being defined in two separate files, we
    # # qualify the output by appending the name of the interface from which it
    # # originates
    methodMap = {}

    # # First check all the requested methods are available and if there are
    # # duplicates then qualify their names for the user
    for method in self.methodsToRun:
      matchingInterfaces = []
      for interface in self.externalInterfaces:
        if method in interface.availableMethods():
          matchingInterfaces.append(interface)


      if len(matchingInterfaces) == 0:
        self.raiseAWarning(method + ' not found. I will skip it.')
      elif len(matchingInterfaces) == 1:
        methodMap[method] = (matchingInterfaces[0], method)
      else:
        outputDict['qualifiedNames'][method] = []
        for interface in matchingInterfaces:
          methodName = interface.name + '.' + method
          methodMap[methodName] = (interface, method)
          outputDict['qualifiedNames'][method].append(methodName)

    # # Evaluate the method and add it to the outputDict, also if the method
    # # adjusts the input data, then you should update it as well.
    for methodName, (interface, method) in methodMap.iteritems():
      outputDict[methodName] = interface.evaluate(method, Input['targets'])
      for target in Input['targets']:
        if hasattr(interface, target):
          outputDict[target] = getattr(interface, target)

    return outputDict

#
#
#
#
class TopologicalDecomposition(BasePostProcessor):
  """
    TopologicalDecomposition class - Computes an approximated hierarchical
    Morse-Smale decomposition from an input point cloud consisting of an
    arbitrary number of input parameters and a response value per input point
  """
  def __init__(self, messageHandler):
    """
     Constructor
     @ In, messageHandler, message handler object
    """

    BasePostProcessor.__init__(self, messageHandler)
    self.acceptedGraphParam = ['approximate knn', 'delaunay', 'beta skeleton', \
                               'relaxed beta skeleton']
    self.acceptedPersistenceParam = ['difference','probability','count']#,'area']
    self.acceptedGradientParam = ['steepest', 'maxflow']
    self.acceptedNormalizationParam = ['feature', 'zscore', 'none']

    # Some default arguments
    self.gradient = 'steepest'
    self.graph = 'beta skeleton'
    self.beta = 1
    self.knn = -1
    self.simplification = 0
    self.persistence = 'difference'
    self.normalization = None
    self.weighted = False
    self.parameters = {}

  def inputToInternal(self, currentInp):
    """
      Function to convert the incoming input into a usable format
      @ In, currentInp : The input object to process
      @ Out, None
    """
    if type(currentInp) == list  : currentInput = currentInp [-1]
    else                         : currentInput = currentInp
    if type(currentInput) == dict:
      if 'features' in currentInput.keys(): return currentInput
    inputDict = {'features':{}, 'targets':{}, 'metadata':{}}
    if hasattr(currentInput, 'type'):
      inType = currentInput.type
    elif type(currentInput).__name__ == 'list':
      inType = 'list'
    else:
      self.raiseAnError(IOError, self.__class__.__name__,
                        ' postprocessor accepts files, HDF5, Data(s) only. ',
                        ' Requested: ', type(currentInput))

    if inType not in ['HDF5', 'PointSet', 'list'] and not isinstance(currentInput,Files.File):
      self.raiseAnError(IOError, self, self.__class__.__name__ + ' post-processor only accepts files, HDF5, or DataObjects! Got ' + str(inType) + '!!!!')
    # FIXME: implement this feature
    if isinstance(currentInput,Files.File):
      if currentInput.subtype == 'csv': pass
    # FIXME: implement this feature
    if inType == 'HDF5': pass  # to be implemented
    if inType in ['PointSet']:
      for targetP in self.parameters['features']:
        if   targetP in currentInput.getParaKeys('input'):
          inputDict['features'][targetP] = currentInput.getParam('input' , targetP)
        elif targetP in currentInput.getParaKeys('output'):
          inputDict['features'][targetP] = currentInput.getParam('output', targetP)
      for targetP in self.parameters['targets']:
        if   targetP in currentInput.getParaKeys('input'):
          inputDict['targets'][targetP] = currentInput.getParam('input' , targetP)
        elif targetP in currentInput.getParaKeys('output'):
          inputDict['targets'][targetP] = currentInput.getParam('output', targetP)
      inputDict['metadata'] = currentInput.getAllMetadata()
    # now we check if the sampler that genereted the samples are from adaptive... in case... create the grid
    if 'SamplerType' in inputDict['metadata'].keys(): pass
    return inputDict

  def _localReadMoreXML(self, xmlNode):
    """
      Function to grab the names of the methods this post-processor will be
      using
      @ In, xmlNode    : Xml element node
      @ Out, None
    """
    for child in xmlNode:
      if child.tag == "graph":
        self.graph = child.text.encode('ascii').lower()
        if self.graph not in self.acceptedGraphParam:
          self.raiseAnError(IOError, 'Requested unknown graph type: ',
                            self.graph, '. Available options: ',
                            self.acceptedGraphParam)
      elif child.tag == "gradient":
        self.gradient = child.text.encode('ascii').lower()
        if self.gradient not in self.acceptedGradientParam:
          self.raiseAnError(IOError, 'Requested unknown gradient method: ',
                            self.gradient, '. Available options: ',
                            self.acceptedGradientParam)
      elif child.tag == "beta":
        self.beta = float(child.text)
        if self.beta <= 0 or self.beta > 2:
          self.raiseAnError(IOError, 'Requested invalid beta value: ',
                            self.beta, '. Allowable range: (0,2]')
      elif child.tag == 'knn':
        self.knn = int(child.text)
      elif child.tag == 'simplification':
        self.simplification = float(child.text)
      elif child.tag == 'persistence':
        self.persistence = child.text.encode('ascii').lower()
        if self.persistence not in self.acceptedPersistenceParam:
          self.raiseAnError(IOError, 'Requested unknown persistence method: ',
                            self.persistence, '. Available options: ',
                            self.acceptedPersistenceParam)
      elif child.tag == 'parameters':
        self.parameters['features'] = child.text.strip().split(',')
        for i, parameter in enumerate(self.parameters['features']):
          self.parameters['features'][i] = self.parameters['features'][i].encode('ascii')
      elif child.tag == 'weighted':
        self.weighted = child.text in ['True', 'true']
      elif child.tag == 'response':
        self.parameters['targets'] = child.text
      elif child.tag == 'normalization':
        self.normalization = child.text.encode('ascii').lower()
        if self.normalization not in self.acceptedNormalizationParam:
          self.raiseAnError(IOError, 'Requested unknown normalization type: ',
                            self.normalization, '. Available options: ',
                            self.acceptedNormalizationParam)

  def collectOutput(self, finishedJob, output):
    """
      Function to place all of the computed data into the output object
      @ In, finishedJob: A JobHandler object that is in charge of running this
                         post-processor
      @ In, output: The object where we want to place our computed results
      @ Out, None
    """
    if finishedJob.returnEvaluation() == -1:
      # TODO This does not feel right
      self.raiseAnError(RuntimeError,'No available output to collect (run probably did not finish yet)')
    inputList = finishedJob.returnEvaluation()[0]
    outputDict = finishedJob.returnEvaluation()[1]

    if type(output).__name__ in ["str", "unicode", "bytes"]:
      self.raiseAWarning('Output type ' + type(output).__name__ + ' not'
                         + ' yet implemented. I am going to skip it.')
    elif output.type == 'Datas':
      self.raiseAWarning('Output type ' + type(output).__name__ + ' not'
                         + ' yet implemented. I am going to skip it.')
    elif output.type == 'HDF5':
      self.raiseAWarning('Output type ' + type(output).__name__ + ' not'
                         + ' yet implemented. I am going to skip it.')
    elif output.type == 'PointSet':
      requestedInput = output.getParaKeys('input')
      requestedOutput = output.getParaKeys('output')
      dataLength = None
      for inputData in inputList:
        # Pass inputs from input data to output data
        for key, value in inputData.getParametersValues('input').items():
          if key in requestedInput:
            # We need the size to ensure the data size is consistent, but there
            # is no guarantee the data is not scalar, so this check is necessary
            myLength = 1
            if hasattr(value, "__len__"):
              myLength = len(value)

            if dataLength is None:
              dataLength = myLength
            elif dataLength != myLength:
              dataLength = max(dataLength, myLength)
              self.raiseAWarning('Data size is inconsistent. Currently set to '
                                 + str(dataLength) + '.')

            for val in value:
              output.updateInputValue(key, val)

        # Pass outputs from input data to output data
        for key, value in inputData.getParametersValues('output').items():
          if key in requestedOutput:
            # We need the size to ensure the data size is consistent, but there
            # is no guarantee the data is not scalar, so this check is necessary
            myLength = 1
            if hasattr(value, "__len__"):
              myLength = len(value)

            if dataLength is None:
              dataLength = myLength
            elif dataLength != myLength:
              dataLength = max(dataLength, myLength)
              self.raiseAWarning('Data size is inconsistent. Currently set to '
                                      + str(dataLength) + '.')

            for val in value:
              output.updateOutputValue(key, val)

        # Append the min/max labels to the data whether the user wants them or
        # not, and place the hierarchy information into the metadata
        for key, value in outputDict.iteritems():
          if key in ['minLabel', 'maxLabel']:
            output.updateOutputValue(key, [value])
          elif key in ['hierarchy']:
            output.updateMetadata(key, [value])
    else:
      self.raiseAnError(IOError,'Unknown output type:',output.type)

  def run(self, InputIn):
    """
     Function to finalize the filter => execute the filtering
     @ In , dictionary       : dictionary of data to process
     @ Out, dictionary       : Dictionary with results
    """
    # # Possibly load this here in case people have trouble building it, so it
    # # only errors if they try to use it?
    from AMSC_Object import AMSC_Object

    Input = self.inputToInternal(InputIn)
    outputDict = {}

    myDataIn = Input['features']
    myDataOut = Input['targets']
    outputData = myDataOut[self.parameters['targets'].encode('UTF-8')]
    self.pointCount = len(outputData)
    self.dimensionCount = len(self.parameters['features'])

    inputData = np.zeros((self.pointCount, self.dimensionCount))
    for i, lbl in enumerate(self.parameters['features']):
      inputData[:, i] = myDataIn[lbl.encode('UTF-8')]

    if self.weighted:
      weights = InputIn[0].getMetadata('PointProbability')
    else:
      weights = None

    names = self.parameters['features'] + [self.parameters['targets']]
    # FIXME: AMSC_Object employs unsupervised NearestNeighbors algorithm from scikit learn.
    #       The NearestNeighbor algorithm is implemented in SupervisedLearning, which requires features and targets by default.
    #       which we don't have here. When the NearestNeighbor is implemented in unSupervisedLearning switch to it.
    self.__amsc = AMSC_Object(X=inputData, Y=outputData, w=weights,
                              names=names, graph=self.graph,
                              gradient=self.gradient, knn=self.knn,
                              beta=self.beta, normalization=self.normalization,
                              persistence=self.persistence, debug=False)

    self.__amsc.Persistence(self.simplification)
    partitions = self.__amsc.Partitions()

    outputDict['minLabel'] = np.zeros(self.pointCount)
    outputDict['maxLabel'] = np.zeros(self.pointCount)
    output = ""
    for extPair, indices in partitions.iteritems():
      for idx in indices:
        outputDict['minLabel'][idx] = extPair[0]
        outputDict['maxLabel'][idx] = extPair[1]
    outputDict['hierarchy'] = self.__amsc.PrintHierarchy()
    output += '========== Linear Regressors: ==========' + os.linesep
    self.__amsc.BuildModels()
    linearFits = self.__amsc.SegmentFitCoefficients()
    linearFitnesses = self.__amsc.SegmentFitnesses()

    for key in linearFits.keys():
      output += str(key) + os.linesep
      coefficients = linearFits[key]
      rSquared = linearFitnesses[key]
      #output += '\t' + u"\u03B2\u0302: " + str(coefficients) + '\n'
      #output += '\t' + u"R\u00B2: " + str(rSquared) + '\n' + '\n'
      output += '\t' + "beta: " + str(coefficients) + os.linesep
      output += '\t' + "R^2: " + str(rSquared) + 2 * os.linesep
      outputDict['coefficients_%d_%d' % (key[0], key[1])] = coefficients
      outputDict['R2_%d_%d' % (key[0], key[1])] = rSquared

    #output += 'RMSD  = %f\n' % (self.linearNRMSD)
    output += '========== Gaussian Fits: ==========' + os.linesep
    #output += u'a/\u221A(2\u03C0^d|\u03A3|)*e^(-(x-\u03BC)T\u03A3(x-\u03BC)) + c - '
    #      + u'a\t(\u03BC & c are fixed, \u03A3 and a are estimated)\n'
    output += 'a/sqrt(2*(pi)^d|M|)*e^(-(x-mu)TM(x-mu)) + c - a'
    output += '\t(mu & c are fixed, M and a are estimated)' + os.linesep

    exts = linearFits.keys()
    exts = [int(item) for sublist in exts for item in sublist]
    exts = list(set(exts))

    for key in exts:
      output += str(key) + ':' + os.linesep
      (mu, c, a, A) = self.__amsc.GetExtremumFitCoefficients(key)
      #output += u':\t\u03BC=' + str(mu) + '\n'
      output += u':\tmu=' + str(mu) + os.linesep
      output += '\tc=' + str(c) + os.linesep
      output += '\ta=' + str(a) + os.linesep
      output += '\tM=' + os.linesep + str(A) + 2 * os.linesep
      #output += '\t\u03A3=\n' + str(A)+'\n\n'
      #output += '\t' + u"R\u00B2: " + str(rSquared) + '\n\n'

      outputDict['mu_' + str(key)] = mu
      outputDict['c_' + str(key)] = c
      outputDict['a_' + str(key)] = a
      outputDict['Sigma_' + str(key)] = A
      outputDict['R2_' + str(key)] = rSquared

    # output += 'RMSD  = %f and %f\n' % (self.gaussianNRMSD[0],self.gaussianNRMSD[1])
    self.raiseAMessage(output)
    return outputDict

"""
 Interface Dictionary (factory) (private)
"""
__base = 'PostProcessor'
__interFaceDict = {}
__interFaceDict['SafestPoint'              ] = SafestPoint
__interFaceDict['LimitSurfaceIntegral'     ] = LimitSurfaceIntegral
__interFaceDict['PrintCSV'                 ] = PrintCSV
__interFaceDict['BasicStatistics'          ] = BasicStatistics
__interFaceDict['LoadCsvIntoInternalObject'] = LoadCsvIntoInternalObject
__interFaceDict['LimitSurface'             ] = LimitSurface
__interFaceDict['ComparisonStatistics'     ] = ComparisonStatistics
__interFaceDict['External'                 ] = ExternalPostProcessor
__interFaceDict['TopologicalDecomposition' ] = TopologicalDecomposition
__knownTypes = __interFaceDict.keys()

def knownTypes():
  return __knownTypes

def returnInstance(Type, caller):
  """
    function used to generate a Filter class
    @ In, Type : Filter type
    @ Out,Instance of the Specialized Filter class
  """
  try: return __interFaceDict[Type](caller.messageHandler)
  except KeyError: caller.raiseAnError(NameError, 'not known ' + __base + ' type ' + Type)
