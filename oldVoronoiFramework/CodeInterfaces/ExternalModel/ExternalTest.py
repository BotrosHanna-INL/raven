'''
Created on Jun 8, 2013

@author: crisr
'''
from __future__ import division, print_function, unicode_literals, absolute_import
import warnings
warnings.simplefilter('default',DeprecationWarning)

import os
import copy
from CodeInterfaceBaseClass import CodeInterfaceBase

class ExternalTest(CodeInterfaceBase):
  def generateCommand(self,inputFiles,executable,flags=None):
    return '', ''
  def findOutputFile(self,command):
    return ''
  def createNewInput(self,currentInputFiles,oriInputFiles,samplerType,**Kwargs):
    return currentInputFiles
  def appendLoadFileExtension(self,fileRoot):
    return fileRoot

