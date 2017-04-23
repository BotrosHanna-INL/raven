'''
Created on April 14, 2014

@author: alfoa
'''
from __future__ import division, print_function, unicode_literals, absolute_import
import warnings
warnings.simplefilter('default',DeprecationWarning)

import os
import sys
import copy
import utils
from utils import toString
import xml.etree.ElementTree as ET
import json
uppath = lambda _path, n: os.sep.join(_path.split(os.sep)[:-n])
import Distributions
from CodeInterfaceBaseClass import CodeInterfaceBase

class RAVENInterface(CodeInterfaceBase):
  '''this class is used as part of a code dictionary to specialize Model.Code for RAVEN'''
  def generateCommand(self,inputFiles,executable,clargs=None,fargs=None):
    """
    See base class.  Collects all the clargs and the executable to produce the command-line call.
    Returns tuple of commands and base file name for run.
    Commands are a list of tuples, indicating parallel/serial and the execution command to use.
    @ In, inputFiles, the input files to be used for the run
    @ In, executable, the executable to be run
    @ In, clargs, command-line arguments to be used
    @ In, fargs, in-file changes to be made
    @Out, tuple( list(tuple(serial/parallel, exec_command)), outFileRoot string)
    """
    found = False
    for index, inputFile in enumerate(inputFiles):
      if inputFile.getExt() in self.getInputExtension():
        found = True
        break
    if not found: raise IOError('None of the input files has one of the following extensions: ' + ' '.join(self.getInputExtension()))

    outputfile = 'out~'+inputFiles[index].getBase()
    if clargs: precommand = executable + clargs['text']
    else     : precommand = executable
    executeCommand = [('parallel',precommand + ' -i '+inputFiles[index].getFilename() +
                      ' Outputs/file_base='+ outputfile +
                      ' Outputs/csv=false' +
                      ' Outputs/checkpoint=true'+
                      ' Outputs/tail/type=ControlLogicBranchingInfo'+
                      ' Outputs/ravenCSV/type=CSVRaven')]
    return executeCommand,outputfile

  def finalizeCodeOutput(self,currentInputFiles,output,workingDir):
    ''' this method is called by the RAVEN code at the end of each run (if the method is present).
        It can be used for those codes, that do not create CSV files to convert the whaterver output formato into a csv
        @ currentInputFiles, Input, the current input files (list)
        @ output, Input, the Output name root (string)
        @ workingDir, Input, actual working dir (string)
        @ return is optional, in case the root of the output file gets changed in this method.
    '''
    return output

  def createNewInput(self,currentInputFiles,oriInputFiles,samplerType,**Kwargs):
    '''this generate a new input file depending on which sampler has been chosen'''
    MOOSEparser = utils.importFromPath(os.path.join(os.path.join(uppath(os.path.dirname(__file__),1),'MooseBasedApp'),'MOOSEparser.py'),False)
    self._samplersDictionary                             = {}
    self._samplersDictionary['MonteCarlo'              ] = self.monteCarloForRAVEN
    self._samplersDictionary['Grid'                    ] = self.gridForRAVEN
    self._samplersDictionary['LimitSurfaceSearch'      ] = self.gridForRAVEN # same Grid Fashion. It forces a dist to give a particular value
    self._samplersDictionary['Stratified'              ] = self.latinHyperCubeForRAVEN
    self._samplersDictionary['DynamicEventTree'        ] = self.dynamicEventTreeForRAVEN
    self._samplersDictionary['FactorialDesign'         ] = self.gridForRAVEN
    self._samplersDictionary['ResponseSurfaceDesign'   ] = self.gridForRAVEN
    self._samplersDictionary['AdaptiveDynamicEventTree'] = self.adaptiveDynamicEventTreeForRAVEN
    self._samplersDictionary['StochasticCollocation'   ] = self.gridForRAVEN
    found = False
    for index, inputFile in enumerate(currentInputFiles):
      if inputFile.getExt() in self.getInputExtension():
        found = True
        break
    if not found: raise IOError('None of the input files has one of the following extensions: ' + ' '.join(self.getInputExtension()))
    parser = MOOSEparser.MOOSEparser(currentInputFiles[index].getAbsFile())
    Kwargs["distributionNode"] = parser.findNodeInXML("Distributions")
    modifDict = self._samplersDictionary[samplerType](**Kwargs)
    parser.modifyOrAdd(modifDict,False)
    newInputFiles = copy.deepcopy(currentInputFiles)
    if type(Kwargs['prefix']) in [str,type("")]:#Specifing string type for python 2 and 3
      newInputFiles[index].setBase(Kwargs['prefix']+"~"+newInputFiles[index].getBase())
    else:
      newInputFiles[index].setBase(str(Kwargs['prefix'][1][0])+'~'+newInputFiles[index].getBase())
    parser.printInput(newInputFiles[index].getAbsFile())
    return newInputFiles

  def monteCarloForRAVEN(self,**Kwargs):
    if 'prefix' in Kwargs: counter = Kwargs['prefix']
    else: raise IOError('a counter is needed for the Monte Carlo sampler for RAVEN')
    if 'initialSeed' in Kwargs: initSeed = Kwargs['initialSeed']
    else                       : initSeed = 1
    _,listDict = self.__genBasePointSampler(**Kwargs)
    #listDict = []
    modifDict = {}
    modifDict['name'] = ['Distributions']
    RNGSeed = int(counter) + int(initSeed) - 1
    modifDict[b'RNG_seed'] = str(RNGSeed)
    listDict.append(modifDict)
    return listDict

  def adaptiveDynamicEventTreeForRAVEN(self,**Kwargs): return self.dynamicEventTreeForRAVEN(**Kwargs)

  def dynamicEventTreeForRAVEN(self,**Kwargs):

    listDict = []
    if 'hybridsamplerCoordinate' in Kwargs.keys():
      for preconditioner in Kwargs['hybridsamplerCoordinate']:
        preconditioner['executable'] = Kwargs['executable']
        if 'MC' in preconditioner['SamplerType']:
          listDict = self.__genBasePointSampler(**preconditioner)[1]
          listDict.extend(self.monteCarloForRAVEN(**preconditioner))
        elif 'Grid' in preconditioner['SamplerType']: listDict.extend(self.gridForRAVEN(**preconditioner))
        elif 'Stratified' in preconditioner['SamplerType'] or 'Stratified' in preconditioner['SamplerType']: listDict.extend(self.latinHyperCubeForRAVEN(**preconditioner))
    # Check the initiator distributions and add the next threshold
    if 'initiatorDistribution' in Kwargs.keys():
      print("figaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
      for i in range(len(Kwargs['initiatorDistribution'])):
        modifDict = {}
        modifDict['name'] = ['Distributions',Kwargs['initiatorDistribution'][i]]
        modifDict['ProbabilityThreshold'] = Kwargs['PbThreshold'][i]
        listDict.append(modifDict)
        del modifDict
    # add the initial time for this new branch calculation
    if 'startTime' in Kwargs.keys():
      if Kwargs['startTime'] != -sys.float_info.max:
        modifDict = {}
        startTime = Kwargs['startTime']
        modifDict['name'] = ['Executioner']
        modifDict['start_time'] = startTime
        listDict.append(modifDict)
        del modifDict
    # create the restart file name root from the parent branch calculation
    # in order to restart the calc from the last point in time
    if 'endTimeStep' in Kwargs.keys():
      #if Kwargs['endTimeStep'] != 0 or Kwargs['endTimeStep'] == 0:

      if Kwargs['startTime'] !=  -sys.float_info.max:
        modifDict = {}
        endTimeStepString = str(Kwargs['endTimeStep'])
        if(Kwargs['endTimeStep'] <= 9999):
          numZeros = 4 - len(endTimeStepString)
          for i in range(numZeros):
            endTimeStepString = "0" + endTimeStepString
        splitted = Kwargs['outfile'].split('~')
        output_parent = splitted[0] + '~' + toString(Kwargs['parentID']) + '~' + splitted[1]
        restartFileBase = output_parent + "_cp/" + endTimeStepString
        modifDict['name'] = ['Executioner']
        modifDict['restart_file_base'] = restartFileBase
        #print(' Restart file name base is "' + restart_file_base + '"')
        listDict.append(modifDict)
        del modifDict
    # max simulation time (if present)
    if 'endTime' in Kwargs.keys():
      modifDict = {}
      endTime = Kwargs['endTime']
      modifDict['name'] = ['Executioner']
      modifDict['end_time'] = endTime
      listDict.append(modifDict)
      del modifDict

    # in this way we erase the whole block in order to neglect eventual older info
    # remember this "command" must be added before giving the info for refilling the block
    modifDict = {}
    modifDict['name'] = ['RestartInitialize']
    modifDict['special'] = set(['erase_block'])
    listDict.append(modifDict)
    del modifDict
    # check and add the variables that have been changed by a distribution trigger
    # add them into the RestartInitialize block
    if 'branchChangedParam' in Kwargs.keys():
      if Kwargs['branchChangedParam'][0] not in ('None',b'None',None):
        for i in range(len(Kwargs['branchChangedParam'])):
          modifDict = {}
          modifDict['name'] = ['RestartInitialize',Kwargs['branchChangedParam'][i]]
          modifDict['value'] = Kwargs['branchChangedParamValue'][i]
          listDict.append(modifDict)
          del modifDict
    return listDict

  def __genBasePointSampler(self,**Kwargs):
    """Figure out which distributions need to be handled by
    the grid or Stratified samplers by modifying distributions in the .i file.
    Let the regular moose point sampler take care of the rest.
    Returns (distributions,listDict) where listDict is the
    start of the listDict that tells how to modify the input, and
    distributions is a dictionary with keys that are the 'variable name'
    and values of [computedValue,distribution name in .i file]
    Note that the key has "<distribution>" in front of the variable name.
    The actual variable can be gotten from the full key by:
    key[len('<distribution>'):]
    TODO This should check that the distributions in the .i file (if
    they exist) are consistent with the ones in the .xml file.
    TODO For variables, it should add them to the .csv file.
    """
    #print("Kwargs",Kwargs,"SampledVars",Kwargs["SampledVars"])
    distributionKeys = [key for key in Kwargs["SampledVars"] if key.startswith("<distribution>")]
    distributions = {}
    #distributionNodeRoot = Kwargs["distributionNode"]
    #print(ET.tostring(distributionNodeRoot))
    for key in distributionKeys:
      distributionName = Kwargs['distributionName'][key]
      distributionType = Kwargs['distributionType'][key]
      crowDistribution = json.loads(Kwargs['crowDist'][key])
      distributions[key] = [Kwargs["SampledVars"].pop(key),distributionName,
                            distributionType,crowDistribution]
      #distributionNode = distributionNodeRoot.find(distributionName)
      #distributionInstance = Distributions.returnInstance(distributionType)
      #distributionInstance._readMoreXML(distributionNode)
      #print(key,distributions[key],distributionNode,crowDistribution)
    mooseInterface = utils.importFromPath(os.path.join(os.path.join(uppath(os.path.dirname(__file__),1),'MooseBasedApp'),'MooseBasedAppInterface.py'),False)

    mooseApp = mooseInterface.MooseBasedAppInterface()
    listDict = mooseApp.pointSamplerForMooseBasedApp(**Kwargs)
    return distributions,listDict

  def gridForRAVEN(self,**Kwargs):
    """Uses point sampler to generate variable points, and
    modifies distributions to be a zerowidth (constant) distribution
    at the grid point.
    """
    distributions,listDict = self.__genBasePointSampler(**Kwargs)
    for key in distributions.keys():
      distName, distType, crowDist = distributions[key][1:4]
      crowDist['name'] = ['Distributions',distName]
      #The following code would check more, but requires floating compare
      # that currently doesn't work properly
      #assertDict = crowDist.copy()
      #assertDict['special'] = set(['assert_match'])
      #listDict.append(assertDict)
      for crowDistKey in crowDist.keys():
        if crowDistKey not in ['type']: listDict.append({'name':['Distributions',distName], 'special':set(['assert_match']), crowDistKey:crowDist[crowDistKey]})

      listDict.append({'name':['Distributions',distName],
                       'special':set(['assert_match']),
                       'type':crowDist['type']})
      listDict.append({'name':['Distributions',distName],'special':set(['erase_block'])})
      listDict.append({'name':['Distributions',distName],'force_value':distributions[key][0]})
      listDict.append(crowDist)
    #print("listDict",listDict,"distributions",distributions,"Kwargs",Kwargs)
    return listDict

  def latinHyperCubeForRAVEN(self,**Kwargs):
    """Uses point sampler to generate variable points, and truncates
    distribution to be inside of the latin hyper cube upper and lower
    bounds.
    """
    distributions,listDict = self.__genBasePointSampler(**Kwargs)
    for key in distributions.keys():
      distName, distType, crowDist = distributions[key][1:4]
      crowDist['name'] = ['Distributions',distName]
      #The following code would check more, but requires floating compare
      # that currently doesn't work properly
      #assertDict = crowDist.copy()
      #assertDict['special'] = set(['assert_match'])
      #listDict.append(assertDict)
      listDict.append({'name':['Distributions',distName],
                       'special':set(['assert_match']),
                       'type':crowDist['type']})
      listDict.append({'name':['Distributions',distName],
                       'special':set(['erase_block'])})
      listDict.append({'name':['Distributions',distName],
                       'V_window_Up':Kwargs['upper'][key]})
      listDict.append({'name':['Distributions',distName],
                       'V_window_Low':Kwargs['lower'][key]})
      listDict.append(crowDist)
    #print("listDict",listDict,"distributions",distributions)
    return listDict
