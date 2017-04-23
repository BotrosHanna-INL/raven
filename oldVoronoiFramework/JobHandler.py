"""
Created on Mar 5, 2013

@author: alfoa, cogljj, crisr
"""
#for future compatibility with Python 3--------------------------------------------------------------
from __future__ import division, print_function, unicode_literals, absolute_import
import warnings
warnings.simplefilter('default',DeprecationWarning)
if not 'xrange' in dir(__builtins__):
  xrange = range
#End compatibility block for Python 3----------------------------------------------------------------

#External Modules------------------------------------------------------------------------------------
try               : import Queue as queue
except ImportError: import queue
import subprocess
import os
import signal
import copy
import sys
import abc
#import logging, logging.handlers
import threading

#External Modules End--------------------------------------------------------------------------------

#Internal Modules------------------------------------------------------------------------------------
import utils
from BaseClasses import BaseType
# for internal parallel
if sys.version_info.major == 2:
  import pp
  import ppserver
else:
  print("pp does not support python3")
# end internal parallel module
import MessageHandler
#Internal Modules End--------------------------------------------------------------------------------

class ExternalRunner(MessageHandler.MessageUser):
  """
  Class for running external codes
  """
  def __init__(self,messageHandler,command,workingDir,bufsize,output=None,metadata=None,codePointer=None):
    """
     Initialize command variable
     @ In, messageHandler, MessageHandler instance, the global RAVEN message handler instance
     @ In, command, list, list of command that needs to be executed
     @ In, workingDir, string, absolute path of the working directory
     @ In, bufsize, int, buffer size for logger
     @ In, output, string, optional, output filename root
     @ In, metadata, dict, optional, dictionary of metadata associated with this ExternalRunner
     @ In, codePointer, CodeInterface instance, optional, instance of the code interface associated with this ExternalRunner
     @ Out, None
    """
    self.codePointerFailed = None
    self.messageHandler = messageHandler
    self.command    = command
    self.bufsize    = bufsize
    workingDirI     = None
    if    output!=None:
      self.output   = output
      if os.path.split(output)[0] != workingDir: workingDirI = os.path.split(output)[0]
      if len(str(output).split("~")) > 1:
        self.identifier =  str(output).split("~")[1]
      else:
        # try to find the identifier in the folder name
        # to eliminate when the identifier is passed from outside
        def splitall(path):
          allparts = []
          while 1:
            parts = os.path.split(path)
            if parts[0] == path:  # sentinel for absolute paths
              allparts.insert(0, parts[0])
              break
            elif parts[1] == path: # sentinel for relative paths
              allparts.insert(0, parts[1])
              break
            else:
              path = parts[0]
              allparts.insert(0, parts[1])
          return allparts
        splitted = splitall(str(output))
        if len(splitted) >= 2: self.identifier= splitted[-2]
        else: self.identifier= 'generalOut'
    else:
      self.output   = os.path.join(workingDir,'generalOut')
      self.identifier = 'generalOut'
    if workingDirI: self.__workingDir = workingDirI
    else          : self.__workingDir = workingDir
    ####### WARNING: THIS DEEPCOPY MUST STAY!!!! DO NOT REMOVE IT ANYMORE. ANDREA #######
    self.__metadata   = copy.deepcopy(metadata)
    ####### WARNING: THIS DEEPCOPY MUST STAY!!!! DO NOT REMOVE IT ANYMORE. ANDREA #######
    self.codePointer  = codePointer

# BEGIN: KEEP THIS COMMENTED PORTION HERE, I NEED IT FOR LATER USE. ANDREA
    # Initialize logger
    #self.logger     = self.createLogger(self.identifier)
    #self.addLoggerHandler(self.identifier, self.output, 100000, 1)
#   def createLogger(self,name):
#     """
#     Function to create a logging object
#     @ In, name: name of the logging object
#     @ Out, logging object
#     """
#     return logging.getLogger(name)
#
#   def addLoggerHandler(self,logger_name,filename,max_size,max_number_files):
#     """
#     Function to create a logging object
#     @ In, logger_name     : name of the logging object
#     @ In, filename        : log file name (with path)
#     @ In, max_size        : maximum file size (bytes)
#     @ In, max_number_files: maximum number of files to be created
#     @ Out, None
#     """
#     hadler = logging.handlers.RotatingFileHandler(filename,'a',max_size,max_number_files)
#     logging.getLogger(logger_name).addHandler(hadler)
#     logging.getLogger(logger_name).setLevel(logging.INFO)
#     return
#
#   def outStreamReader(self, out_stream):
#     """
#     Function that logs every line received from the out stream
#     @ In, out_stream: output stream
#     @ In, logger    : the instance of the logger object
#     @ Out, logger   : the logger itself
#     """
#     while True:
#       line = out_stream.readline()
#       if len(line) == 0 or not line:
#         break
#       self.logger.info('%s', line)
#       #self.logger.debug('%s', line.srip())
#   END: KEEP THIS COMMENTED PORTION HERE, I NEED IT FOR LATER USE. ANDREA

  def isDone(self):
    """
     Function to inquire the process to check if the calculation is finished
     @ In, None
     @ Out, finished, bool, is this run finished?
    """
    self.__process.poll()
    return self.__process.returncode != None

  def getReturnCode(self):
    """
     Function to inquire the process to get the return code
     If the self.codePointer is available (!= None), this method
     inquires it to check if the process return code is a false negative (or positive).
     The first time the codePointer is inquired, it calls the function and store the result
     => sub-sequential calls to getReturnCode will not inquire the codePointer anymore but
     just return the stored value
     @ In, None
     @ Out, returnCode, int, return code
    """
    returnCode = self.__process.returncode
    if self.codePointer != None:
      if 'checkForOutputFailure' in dir(self.codePointer):
        if  self.codePointerFailed == None: self.codePointerFailed = self.codePointer.checkForOutputFailure(self.output,self.getWorkingDir())
      if self.codePointerFailed: returnCode = 1
    return returnCode

  def returnEvaluation(self):
    """
     Function to return the External runner evaluation (outcome/s). Since in process, return None
     @ In, None
     @ Out, None
    """
    return None

  def returnMetadata(self):
    """
     Function to return the External runner metadata
     @ In, None
     @ Out, __metadata, dict, return the dictionary of metadata associated with this ExternalRunner
    """
    return self.__metadata

  def start(self):
    """
     Function to run the driven code
     @ In, None
     @ Out, None
    """
    oldDir = os.getcwd()
    os.chdir(self.__workingDir)
    localenv = dict(os.environ)
    outFile = open(self.output,'w', self.bufsize)
    self.__process = utils.pickleSafeSubprocessPopen(self.command,shell=True,stdout=outFile,stderr=outFile,cwd=self.__workingDir,env=localenv)
    os.chdir(oldDir)

  def kill(self):
    """
     Function to kill the subprocess of the driven code
     @ In, None
     @ Out, None
    """
    self.raiseAMessage("Terminating "+self.__process.pid+' '+self.command)
    self.__process.terminate()

  def getWorkingDir(self):
    """
     Function to get the working directory path
     @ In, None
     @ Out, __workingDir, string, working directory
    """
    return self.__workingDir

  def getOutputFilename(self):
    """
     Function to get the output filenames
     @ In, None
     @ Out, self.output, string, output filename root
    """
    return os.path.join(self.__workingDir,self.output)
#
#
#
#
class InternalRunner(MessageHandler.MessageUser):
  """
  Class for running internal objects
  """
  def __init__(self,messageHandler,ppserver, Input, functionToRun, frameworkModules = [], identifier=None, metadata=None, functionToSkip = None, forceUseThreads = False):
    """
     Init method
     @ In, messageHandler, MessageHandler object, the global RAVEN message handler object
     @ In, ppserver, ppserver, instance of the ppserver object
     @ In, Input, list, list of inputs that are going to be passed to the function as *args
     @ In, functionToRun, method or function, function that needs to be run
     @ In, frameworkModules, list, optional, list of modules that need to be imported for internal parallelization (parallel python).
                                             this list should be generated with the method returnImportModuleString in utils.py
     @ In, identifier, string, optional, id of this job
     @ In, metadata, dict, optional, dictionary of metadata associated with this run
     @ In, functionToSkip, list, optional, list of functions, classes and modules that need to be skipped in pickling the function dependencies
     @ In, forceUseThreads, bool, optional, flag that, if True, is going to force the usage of multi-threading even if parallel python is activated
     @ Out, None
    """
    # we keep the command here, in order to have the hook for running exec code into internal models
    self.command  = "internal"
    self.messageHandler = messageHandler
    self.ppserver = ppserver
    self.__thread = None
    if    identifier!=None:
      if "~" in identifier: self.identifier =  str(identifier).split("~")[1]
      else                : self.identifier =  str(identifier)
    else: self.identifier = 'generalOut'
    if type(Input) != tuple: self.raiseAnError(IOError,"The input for InternalRunner needs to be a tuple!!!!")
    #the Input needs to be a tuple. The first entry is the actual input (what is going to be stored here), the others are other arg the function needs
    if self.ppserver == None or forceUseThreads: self.subque = queue.Queue()
    self.functionToRun    = functionToRun
    self.__runReturn      = None
    self.__hasBeenAdded   = False
    self.__forceUseThreads= forceUseThreads
    self.__input          = copy.copy(Input)
    self.__metadata       = copy.copy(metadata)
    self.__frameworkMods  = copy.copy(frameworkModules)
    self._functionToSkip  = functionToSkip
    self.retcode          = 0

  def __deepcopy__(self,memo):
    """
     This is the method called with copy.deepcopy.  Overwritten to remove some keys.
     @ In, memo, dict, dictionary required by deepcopy method
     @ Out, newobj, object, deep copy of this object
    """
    cls = self.__class__
    newobj = cls.__new__(cls)
    memo[id(self)] = newobj
    copydict = self.__dict__
    ### these things can't be deepcopied ###
    toRemove = ['functionToRun','subque','_InternalRunner__thread']
    for k,v in copydict.items():
      if k in toRemove: continue
      setattr(newobj,k,copy.deepcopy(v,memo))
    return newobj

  def startParallelPython(self):
    """
     Method to start the calculation associated with this InternalRunner is finished
     @ In, None
     @ Out, None
    """
    if self.ppserver != None and not self.__forceUseThreads:
      if len(self.__input) == 1: self.__thread = self.ppserver.submit(self.functionToRun, args= (self.__input[0],), depfuncs=(), modules = tuple(list(set(self.__frameworkMods))),functionToSkip=self._functionToSkip)
      else                     : self.__thread = self.ppserver.submit(self.functionToRun, args= self.__input, depfuncs=(), modules = tuple(list(set(self.__frameworkMods))),functionToSkip=self._functionToSkip)
    else:
      if len(self.__input) == 1: self.__thread = threading.Thread(target = lambda q,  arg : q.put(self.functionToRun(arg)), name = self.identifier, args=(self.subque,self.__input[0]))
      else                     : self.__thread = threading.Thread(target = lambda q, *arg : q.put(self.functionToRun(*arg)), name = self.identifier, args=(self.subque,)+tuple(self.__input))
      self.__thread.daemon = True
      self.__thread.start()

  def isDone(self):
    """
     Method to check if the calculation associated with this InternalRunner is finished
     @ In, None
     @ Out, finished, bool, is it finished?
    """
    if self.__thread == None: return True
    else:
      if self.ppserver != None and not self.__forceUseThreads: return self.__thread.finished
      else                                                   : return not self.__thread.is_alive()

  def getReturnCode(self):
    """
     Returns the return code from running the code.  If return code not yet set, set it.
     @ In, None
     @ Out, return code, int,  the return code of this evaluation
    """
    if self.ppserver is None and hasattr(self,'subque'):
      if self.subque.empty(): #is this necessary and sufficient for all failed runs?
        self.__runReturn = -1
        self.retcode = -1
    return self.retcode

  def returnEvaluation(self):
    """
     Method to return the results of the function evaluation associated with this InternalRunner
     @ In, None
     @ Out, (Input,response), tuple, tuple containing the results of the evaluation (list of Inputs, function return value)
    """
    if self.isDone():
      if not self.__hasBeenAdded:
        if self.ppserver is not None and not self.__forceUseThreads:
          self.ppserver.print_stats()
          self.__runReturn = self.__thread()
        else:
          if self.subque.empty(): self.__runReturn = None #queue is empty!
          else: self.__runReturn = self.subque.get(timeout=1)
        self.__hasBeenAdded = True
        if self.__runReturn is None:
          self.retcode = -1
          return self.retcode
      return (self.__input[0],self.__runReturn)
    else: return -1 #control return code

  def returnMetadata(self): return self.__metadata

  def start(self):
    """
     Method to start the job associated to this InternalRunner
     @ In, None
     @ Out, None
    """
    try: self.startParallelPython()
    except Exception as ae:
      self.raiseAMessage("InternalRunner job "+self.identifier+" failed with error:"+ str(ae) +" !",'ExceptedError')
      self.retcode = -1

  def kill(self):
    """
     Method to kill the job associated to this InternalRunner
     @ In, None
     @ Out, None
    """
    self.raiseAMessage("Terminating "+self.__thread.pid+ " Identifier " + self.identifier)
    if self.ppserver != None and not self.__forceUseThreads: os.kill(self.__thread.tid,signal.SIGTERM)
    else                                                   : os.kill(self.__thread.pid,signal.SIGTERM)

class JobHandler(MessageHandler.MessageUser):
  def __init__(self):
    """
     Init method
     @ In, None
     @ Out, None
    """
    self.printTag               = 'Job Handler'
    self.runInfoDict            = {}
    self.mpiCommand             = ''
    self.threadingCommand       = ''
    self.initParallelPython     = False
    self.submitDict             = {}
    self.submitDict['External'] = self.addExternal
    self.submitDict['Internal'] = self.addInternal
    self.externalRunning        = []
    self.internalRunning        = []
    self.__running              = []
    self.__queue                = queue.Queue()
    self.__nextId               = 0
    self.__numSubmitted         = 0
    self.__numFailed            = 0
    self.__failedJobs           = {} #dict of failed jobs, keyed on identifer, valued on metadata

  def initialize(self,runInfoDict,messageHandler):
    """
     Method to initialize the JobHandler
     @ In, runInfoDict, dict, dictionary of run info settings
     @ In, messageHandler, MessageHandler object, instance of the global RAVEN message handler
     @ Out, None
    """
    self.runInfoDict = runInfoDict
    self.messageHandler = messageHandler
    if self.runInfoDict['NumMPI'] !=1 and len(self.runInfoDict['ParallelCommand']) > 0:
      self.mpiCommand = self.runInfoDict['ParallelCommand']+' '+str(self.runInfoDict['NumMPI'])
    if self.runInfoDict['NumThreads'] !=1 and len(self.runInfoDict['ThreadingCommand']) > 0:
      self.threadingCommand = self.runInfoDict['ThreadingCommand'] +' '+str(self.runInfoDict['NumThreads'])
    #initialize PBS
    self.__running = [None]*self.runInfoDict['batchSize']

  def __initializeParallelPython(self):
    """
      Internal method that is aimed to initialize the internal parallel system.
      It initilizes the paralle python implementation (with socketing system) in case
      RAVEN is run in a cluster with multiple nodes or the NumMPI > 1,
      otherwise multi-threading is used.
      @ In, None
      @ Out, None
    """
    # check if the list of unique nodes is present and, in case, initialize the socket
    if self.runInfoDict['internalParallel']:
      import random
      if len(self.runInfoDict['Nodes']) > 0:
        availableNodes            = [nodeid.strip() for nodeid in self.runInfoDict['Nodes']]
        # set initial port randomly among the user accessable ones
        randomPort = random.randint(1024,65535)
        # get localHost and servers
        localHostName, ppservers = self.__runRemoteListeningSockets(randomPort)
        self.raiseADebug("Local host is "+ localHostName)
        if len(ppservers) == 0:
          # we are in a single node
          self.ppserver = pp.Server(ncpus=len(availableNodes))
        else:
          # multiple nodes
          self.raiseADebug("Servers found are " + ','.join(ppservers))
          self.raiseADebug("Server port in use is " + str(randomPort))
          self.ppserver = pp.Server(ncpus=0, ppservers=tuple(ppservers))
      else: self.ppserver = pp.Server(ncpus=int(self.runInfoDict['totalNumCoresUsed'])) # we use the parallel python
    else: self.ppserver = None # we just use threading!
    self.initParallelPython = True

  def __getLocalAndRemoteMachineNames(self):
    """
      Method to get the qualified host and remote nodes' names
      @ In, None
      @ Out, hostNameMapping, dict, dictionary containing the qualified names {'local':hostName,'remote':{nodeName1:IP1,nodeName2:IP2,etc}}
    """
    import socket
    hostNameMapping = {'local':"",'remote':{}}
    # get local machine name
    hostNameMapping['local'] =  str(socket.getfqdn()).strip()
    self.raiseADebug("Local Host is " + hostNameMapping['local'])
    # collect the qualified hostnames
    for nodeid in list(set(self.runInfoDict['Nodes'])):
      hostNameMapping['remote'][nodeid.strip()] = socket.gethostbyname(nodeid.strip())
      self.raiseADebug("Remote Host identified " + hostNameMapping['remote'][nodeid.strip()])
    return hostNameMapping

  def __runRemoteListeningSockets(self,newPort):
    """
      Method to activate the remote sockets for parallel python
      @ In, newPort, integer, the comunication port to use
      @ Out, (qualifiedHostName, ppservers), tuple, tuple containining:
             - in position 0 the host name and
             - in position 1 the list containing the nodes in which the remote sockets have been activated
    """
    # get the local machine name and the remote nodes one
    hostNameMapping = self.__getLocalAndRemoteMachineNames()
    qualifiedHostName, remoteNodesIP =  hostNameMapping['local'], hostNameMapping['remote']
    # strip out the nodes' names
    availableNodes = [node.strip() for node in self.runInfoDict['Nodes']]
    # get unique nodes
    uniqueNodes    = list(set(availableNodes))
    ppservers      = []
    if len(uniqueNodes) > 1:
      # there are remote nodes that need to be activated
      # locate the ppserver script and add the path
      ppserverScript = os.path.join(self.runInfoDict['FrameworkDir'],"contrib","pp","ppserver.py")
      # get the localenv
      localenv = os.environ.copy()
      # modify the python path
      pathSeparator = os.pathsep
      localenv["PYTHONPATH"] = pathSeparator.join(sys.path)
      for nodeid in list(set(availableNodes)):
        outFile = open(os.path.join(self.runInfoDict['WorkingDir'],nodeid.strip()+"_port:"+str(newPort)+"_server_out.log"),'w')
        # check how many processors are available in the node
        ntasks = availableNodes.count(nodeid)
        remoteHostName =  remoteNodesIP[nodeid]
        # activate the remote socketing system
        #Next line is a direct execute of ppserver:
        #subprocess.Popen(['ssh', nodeid, "python2.7", ppserverScript,"-w",str(ntasks),"-i",remoteHostName,"-p",str(newPort),"-t","1000","-g",localenv["PYTHONPATH"],"-d"],shell=False,stdout=outFile,stderr=outFile,env=localenv)
        command=" ".join(["python",ppserverScript,"-w",str(ntasks),"-i",remoteHostName,"-p",str(newPort),"-t","1000","-g",localenv["PYTHONPATH"],"-d"])
        utils.pickleSafeSubprocessPopen(['ssh',nodeid,"COMMAND='"+command+"'",self.runInfoDict['RemoteRunCommand']],shell=False,stdout=outFile,stderr=outFile,env=localenv)
        #ssh nodeid COMMAND='python ppserverScript -w stuff'
        # update list of servers
        ppservers.append(nodeid+":"+str(newPort))
    return qualifiedHostName, ppservers

  def addExternal(self,executeCommands,outputFile,workingDir,metadata=None,codePointer=None):
    """
      Method to add an external runner (an external code) in the handler list
      @ In, executeCommands, tuple(string), ('parallel'/'serial', <execution command>)
      @ In, outputFile, string, output file name
      @ In, workingDir, string, working directory
      @ In, metadata, dict, optional, dictionary of metadata
      @ In, codePointer, derived CodeInterfaceBaseClass object, optional, pointer to code interface
      @ Out, None
    """
    precommand = self.runInfoDict['precommand'] #FIXME what uses this?  Still precommand for whole line if multiapp case?
    #it appears precommand is usually used for mpiexec - however, there could be other uses....
    commands=[]
    for runtype,cmd in executeCommands:
      newcom=''
      if runtype.lower() == 'parallel':
        newcom += precommand
        if self.mpiCommand !='':
          newcom += ' '+self.mpiCommand+' '
        if self.threadingCommand !='': #FIXME are these two exclusive?
          newcom += ' '+ self.threadingCommand +' '
        newcom += cmd+' '
        newcom+= self.runInfoDict['postcommand']
        commands.append(newcom)
      elif runtype.lower() == 'serial':
        commands.append(cmd)
      else:
        self.raiseAnError(IOError,'For execution command <'+cmd+'> the run type was neither "serial" nor "parallel"!  Instead got:',runtype,'\nCheck the code interface.')
    command= ' && '.join(commands)+' '
    self.__queue.put(ExternalRunner(self.messageHandler,command,workingDir,self.runInfoDict['logfileBuffer'],outputFile,metadata,codePointer))
    self.raiseAMessage('Execution command submitted:',command)
    self.__numSubmitted += 1
    if self.howManyFreeSpots()>0: self.addRuns()

  def addInternal(self,Input,functionToRun,identifier,metadata=None, modulesToImport = [], forceUseThreads = False):
    """
     Method to add an internal run (function execution)
     @ In, Input, list, list of Inputs that are going to be passed to the function to be executed as *args
     @ In, functionToRun,function or method, the function that needs to be executed
     @ In, identifier, string, the job identifier
     @ In, metadata, dict, optional, dictionary of metadata associated to this run
     @ In, modulesToImport, list, optional, list of modules that need to be imported for internal parallelization (parallel python).
                                            this list should be generated with the method returnImportModuleString in utils.py
     @ In, forceUseThreads, bool, optional, flag that, if True, is going to force the usage of multi-threading even if parallel python is activated
     @ Out, None
    """
    #internal serve is initialized only in case an internal calc is requested
    if not self.initParallelPython: self.__initializeParallelPython()
    self.__queue.put(InternalRunner(self.messageHandler,self.ppserver, Input, functionToRun, modulesToImport, identifier, metadata, functionToSkip=[utils.metaclass_insert(abc.ABCMeta,BaseType)],forceUseThreads = forceUseThreads))
    self.__numSubmitted += 1
    if self.howManyFreeSpots()>0: self.addRuns()

  def isFinished(self):
    """
     Method to check if all the runs in queue are finished
     @ In, None
     @ Out, isFinished, bool, True all the runs in the queue are finished
    """
    if not self.__queue.empty():
      return False
    for i in range(len(self.__running)):
      if self.__running[i] and not self.__running[i].isDone():
        return False
    return True

  def getNumberOfFailures(self):
    """
     Method to get the number of execution that failed
     @ In, None
     @ Out, __numFailed, int, number of failure
    """
    return self.__numFailed

  def getListOfFailedJobs(self):
    """
     Method to get list of failed jobs
     @ In, None
     @ Out, __failedJobs, list, list of the identifiers (jobs) that failed
    """
    return self.__failedJobs

  def howManyFreeSpots(self):
    """
     Method to get the number of free spots in the running queue
     @ In, None
     @ Out, cnt_free_spots, int, number of free spots
    """
    cntFreeSpots = 0
    if self.__queue.empty():
      for i in range(len(self.__running)):
        if self.__running[i]:
          if self.__running[i].isDone():
            cntFreeSpots += 1
        else:
          cntFreeSpots += 1
    return cntFreeSpots

  def getFinished(self, removeFinished=True, prefix=None):
    """
     Method to get the list of jobs that ended (list of objects)
     @ In, removeFinished, bool, optional, flag to control if the finished jobs need to be removed from the queue
     @ In, prefix, string, optional, if specified only collects finished runs with a particular prefix.
     @ Out, list, list of finished jobs (InternalRunner or ExternalRunner objects)
    """
    finished = []
    for i in range(len(self.__running)):
      if self.__running[i] and self.__running[i].isDone():
        if prefix is not None:
          if self.__running[i].identifier.startswith(prefix):
            finished.append(self.__running[i])
          else:
            continue
        else:
          finished.append(self.__running[i])
        if removeFinished:
          running = self.__running[i]
          returncode = running.getReturnCode()
          if returncode != 0:
            self.raiseAMessage(" Process Failed "+str(running)+' '+str(running.command)+" returncode "+str(returncode))
            self.__numFailed += 1
            self.__failedJobs[running.identifier]=(returncode,copy.deepcopy(running.returnMetadata()))
            if type(running).__name__ == "External":
              outputFilename = running.getOutputFilename()
              if os.path.exists(outputFilename): self.raiseAMessage(open(outputFilename,"r").read())
              else: self.raiseAMessage(" No output "+outputFilename)
          else:
            if self.runInfoDict['delSucLogFiles'] and running.__class__.__name__ != 'InternalRunner':
              self.raiseAMessage(' Run "' +running.identifier+'" ended smoothly, removing log file!')
              if os.path.exists(running.getOutputFilename()): os.remove(running.getOutputFilename())
            if len(self.runInfoDict['deleteOutExtension']) >= 1 and running.__class__.__name__ != 'InternalRunner':
              for fileExt in self.runInfoDict['deleteOutExtension']:
                if not fileExt.startswith("."): fileExt = "." + fileExt
                filelist = [ f for f in os.listdir(running.getWorkingDir()) if f.endswith(fileExt) ]
                for f in filelist: os.remove(f)
          self.__running[i] = None
    if not self.__queue.empty(): self.addRuns()
    return finished

  def addRuns(self):
    """
     Method to start running the jobs in queue
     @ In, None
     @ Out, None
    """
    for i in range(len(self.__running)):
      if self.__running[i] == None and not self.__queue.empty():
        item = self.__queue.get()
        if "External" in item.__class__.__name__ :
          command = item.command
          command = command.replace("%INDEX%",str(i))
          command = command.replace("%INDEX1%",str(i+1))
          command = command.replace("%CURRENT_ID%",str(self.__nextId))
          command = command.replace("%CURRENT_ID1%",str(self.__nextId+1))
          command = command.replace("%SCRIPT_DIR%",self.runInfoDict['ScriptDir'])
          command = command.replace("%FRAMEWORK_DIR%",self.runInfoDict['FrameworkDir'])
          command = command.replace("%WORKING_DIR%",item.getWorkingDir())
          command = command.replace("%BASE_WORKING_DIR%",self.runInfoDict['WorkingDir'])
          command = command.replace("%METHOD%",os.environ.get("METHOD","opt"))
          command = command.replace("%NUM_CPUS%",str(self.runInfoDict['NumThreads']))
          item.command = command
        self.__running[i] = item
        self.__running[i].start() #FIXME this call is really expensive; can it be reduced?
        self.__nextId += 1

  def getFinishedNoPop(self):
    """
     Method to get the list of jobs that ended (list of objects) without removing them from the queue
     @ In, None
     @ Out, finished, list, list of finished jobs (InternalRunner or ExternalRunner objects)
    """
    return self.getFinished(False)

  def getNumSubmitted(self):
    """
     Method to get the number of submitted jobs
     @ In, None
     @ Out, __numSubmitted, int, number of submitted jobs
    """
    return self.__numSubmitted

  def startingNewStep(self):
    """
     Method to reset the __numSubmitted counter
     @ In, None
     @ Out, None
    """
    self.__numSubmitted = 0

  def terminateAll(self):
    """
     Method to clear out the queue
     @ In, None
     @ Out, None
    """
    while not self.__queue.empty(): self.__queue.get()
    for i in range(len(self.__running)):
      if self.__running[i] is not None: self.__running[i].kill()

  def numRunning(self):
    """
    Returns the number of runs currently running.
    @ In, None
    @ Out, int, number of active runs
    """
    return sum(run is not None for run in self.__running)
