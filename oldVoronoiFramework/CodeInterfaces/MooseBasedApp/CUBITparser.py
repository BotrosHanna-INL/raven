"""
created on Jul 15, 2015

@author: tompjame
"""
from __future__ import division, print_function, unicode_literals, absolute_import
import warnings
warnings.simplefilter('default',DeprecationWarning)
if not 'xrange' in dir(__builtins__):
  xrange = range

import os
import sys
import copy
import re
import collections
from utils import toBytes, toStrish, compare

class CUBITparser():
  """Import Cubit journal file input, provide methods to add/change entries and print input back"""

  def __init__(self,inputFile):
    """Open and read file content into an ordered dictionary
       @ In, inputFile, object with information about the template input file
    """
    self.printTag = 'CUBIT_PARSER'
    if not os.path.exists(inputFile.getAbsFile()): raise IOError('Input file not found: '+inputFile.getAbsFile())
    # Initialize file dictionary, storage order, and internal variables
    self.keywordDictionary = collections.OrderedDict()
    self.fileOrderStorage = []

    between_str = ''
    dict_stored = False

    # Open file
    self.inputfile = inputFile.getAbsFile()

    # Generate Global Input Dictionary
    for line in inputFile:
      clear_ws = line.replace(" ", "")
      if clear_ws.startswith('#{'):
        # Catch Aprepro logic
        if 'else' in line or 'ifdef' in line or 'ifndef' in line or 'endif' in line or 'Loop' in line or 'EndLoop' in line:
          between_str += line
        elif'=' in line:
          splitline_clear_ws = re.split('{|<|>|=|}|!', clear_ws)
          splitline = re.split('{|<|>|=|}|!', line)
          # Catch Aprepro if logic
          if splitline_clear_ws[1] != splitline[1].strip():
            between_str += line
          elif splitline_clear_ws[1] == splitline[1].strip():
            if len(between_str) > 0: self.fileOrderStorage.append(between_str); between_str = ''
            if dict_stored == False: self.fileOrderStorage.append(['dict_location']); dict_stored = True
            beg_garb, keywordAndValue, end_garb = re.split('#{|}',clear_ws)
            varname, varvalue = keywordAndValue.split('=')
            self.keywordDictionary[varname] = varvalue
      else:
        between_str += line
    if len(between_str) > 0: self.fileOrderStorage.append(between_str)

  def modifyInternalDictionary(self,**inDictionary):
    """Parse the input dictionary and replace matching keywords in internal dictionary.
       @ In, inDictionary, Dictionary containing full longform name and raven sampled var value
    """
    for keyword, newvalue in inDictionary.items():
      garb, keyword = keyword.split('|')
      self.keywordDictionary[keyword] = newvalue

  def writeNewInput(self,outfile=None):
    """Using the fileOrderStorage list, reconstruct the template input with modified
       keywordDictionary.
    """
    if outfile == None: outfile = self.inputfile
    IOfile = open(outfile,'w')
    for e, entry in enumerate(self.fileOrderStorage):
      if type(entry) == unicode:
        IOfile.writelines(entry)
      elif type(entry) == list:
        for key, value in self.keywordDictionary.items():
          IOfile.writelines('#{ '+key+' = '+str(value)+'}'+'\n')
    IOfile.close()
