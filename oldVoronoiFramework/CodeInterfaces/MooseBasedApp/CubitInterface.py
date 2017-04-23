"""
created on July 16, 2015

@author: tompjame
"""
from __future__ import division, print_function, unicode_literals, absolute_import
import warnings
warnings.simplefilter('default', DeprecationWarning)

import os
import copy
import sys
import re
from subprocess import Popen
import collections
from utils import toBytes, toStrish, compare
from CodeInterfaceBaseClass import CodeInterfaceBase

class CubitInterface(CodeInterfaceBase):
  """This class is used to couple raven to Cubit journal files for input to generate
     meshes (usually to run in another simulation)"""

  def generateCommand(self, inputFiles, executable, clargs=None, fargs=None):
    """Generate a command to run cubit using an input with sampled variables to output
       the perturbed mesh as an exodus file.
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
    executeCommand = [('serial',executable+ ' -batch ' + inputFiles[index].getFilename())]
    return executeCommand, self.outputfile

  def createNewInput(self, currentInputFiles, oriInputFiles, samplerType, **Kwargs):
    """Generates new perturbed input files.
       @ In, currentInputFiles, list of Files objects, most recently perturbed files
       @ In, originInputFiles, the template input files originally shown
       @ In, samplerType, the sampler type used (not used in this algorithm)
       @ In, Kwargs, dictionary of key-val pairs
       @Out, list of perturbed files
    """
    import CUBITparser
    for index, inputFile in enumerate(oriInputFiles):
      if inputFile.getExt() == self.getInputExtension():
        break
    parser = CUBITparser.CUBITparser(currentInputFiles[index])
    # Copy original mesh generation input file and write new input from sampled vars
    newInputFiles = copy.deepcopy(currentInputFiles)
    newInputFiles[index].close()
    newInputFiles[index].setBase(currentInputFiles[index].getBase()+'_'+Kwargs['prefix'])
    self.outputfile = 'mesh~'+newInputFiles[index].getBase()
    Kwargs['SampledVars']['Cubit|out_name'] = "\"'"+self.outputfile+".e'\""
    # Copy dictionary of sampled vars sent to interface and change name of alias (if it exists)
    sampledDict = copy.deepcopy(Kwargs['SampledVars'])
    for alias,var in Kwargs['alias'].items():
      sampledDict[var] = Kwargs['SampledVars'][alias]
      del sampledDict[alias]
    parser.modifyInternalDictionary(**sampledDict)
    # Write new input files
    parser.writeNewInput(newInputFiles[index].getAbsFile())
    return newInputFiles

  def getInputExtension(self):
    """Returns the output extension of input files to be perturbed as a string."""
    return("jou")

  def finalizeCodeOutput(self, command, output, workingDir):
    """Cleans up files in the working directory that are not needed after the run
       @ In, command, (string), command used to run the just ended job
       @ In, output, (string), the Output name root
       @ In, workingDir, (string), the current working directory
       @Out, None
    """
    # Append wildcard strings to workingDir for files wanted to be removed
    cubitjour_files = os.path.join(workingDir,'cubit*')
    # Inform user which files will be removed
    print('Interface attempting to remove files: \n'+cubitjour_files)
    # Remove Cubit generated journal files
    self.rmUnwantedFiles(cubitjour_files)

  def rmUnwantedFiles(self, path_to_files):
    """Method to remove unwanted files after completing the run
       @ In, path_to_files, (string), path to the files to be removed
       @Out, None
    """
    try:
      p = Popen('rm '+path_to_files)
    except OSError as e:
      print('  ...',"There was an error removing ",path_to_files,'<',e,'>','but continuing onward...')
