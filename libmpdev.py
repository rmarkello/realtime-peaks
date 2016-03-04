#!/usr/bin/env python
#created by Edwin Dalmaijer (esdalmaijer)
#edits by Ross Markello (rmarkello)

import os
import copy
import time
import numpy as np
from threading import Thread, Lock
import multiprocessing as mp

if os.name != 'posix':
    from ctypes import windll, c_int, c_double, byref
else:
    raise Exception("Sorry Mac/Linux/POSIX user: you have to use Windows to work with the BioPac!")

try:
    mpdev = windll.LoadLibrary('mpdev.dll')
except:
    try:
        mpdev = windll.LoadLibrary(os.path.join(os.path.dirname(os.path.abspath(__file__)),'mpdev.dll'))
    except:
        raise Exception("Error in libmpdev: could not load mpdev.dll")


# error handling
def check_returncode(returncode):
    """
    desc:
        Checks a BioPac MP150 returncode, and returns it's meaning as a human readable string

    arguments:
        returncode:
            desc:    A code returned by one of the functions from the mpdev DLL
            type:    int

    returns:
        desc:    A string describing the error
        type:    str
    """

    if returncode == 1:
        meaning = "MPSUCCESS"
    else:
        meaning = "UNKNOWN"

    return meaning


# class definition
class MP150:
    """
    desc:
        Class to communicate with BioPax MP150 Squeezies.
    """
    
    def __init__(self, logfile='default', samplerate=200, channels=[1,2,3], pipe=False):
        """
        desc:
            Finds an MP150, and initializes a connection.
        
        keywords:
            logfile:
                desc:Name of the logfile (optionally with path), which will
                    be used to create a textfile, e.g.
                    'default_MP150_data.tsv' (default = 'default')
                type:str
            samplerate:
                desc:The sampling rate in Hertz (default = 200).
                type:int
            channels:
                desc:Which channels to record from (default = 1, 2, 3)
                type:list
        """
        
        self._manager = mp.Manager()
        self._dict = self._manager.dict()
        self._loglock = self._manager.Lock()
        
        # settings
        self._samplerate = samplerate
        self._sampletime = 1000.0 / self._samplerate
        self._sampletimesec = self._sampletime / 1000.0
        self._dict['logfilename'] = "%s_MP150_data.csv" % (logfile)

        # connect to the MP150
        # (101 is the code for the MP150, 103 for the MP36R)
        # (11 is a code for the communication method)
        # ('auto' is for automatically connecting to the first responding device)
        try:
            result = mpdev.connectMPDev(c_int(101), c_int(11), b'auto')
        except:
            result = "failed to call connectMPDev"
        if check_returncode(result) != "MPSUCCESS":
            raise Exception("Error in libmpdev: failed to connect to the MP150: %s" % result)
        
        # get starting time
        self._dict['start_time'] = time.time()
        
        # set sampling rate
        try:
            result = mpdev.setSampleRate(c_double(self._sampletime))
        except:
            result = "failed to call setSampleRate"
        if check_returncode(result) != "MPSUCCESS":
            raise Exception("Error in libmpdev: failed to set samplerate: %s" % result)
        
        # set Channels to acquire
        try:
            chnls = np.zeros(12,dtype='int64')
            chnls[np.array(channels) - 1] = 1
            self._dict['channels'] = chnls
            chnls = (c_int * len(chnls))(*chnls)
            result = mpdev.setAcqChannels(byref(chnls))
        except:
            result = "failed to call setAcqChannels"
        if check_returncode(result) != "MPSUCCESS":
            raise Exception("Error in libmpdev: failed to set channels to acquire: %s" % result)
        
        # start acquisition
        try:
            result = mpdev.startAcquisition()
        except:
            result = "failed to call startAcquisition"
        if check_returncode(result) != "MPSUCCESS":
            raise Exception("Error in libmpdev: failed to start acquisition: %s" % result)
       
        # open log file
        #self._logfile = open(self._logfilename, 'w')
        
        # write header
        #header = "timestamp"
        #for x in range(len(channels)):
        #    header = ",".join([header,'channel_'+str(channels[x])])
        #self._logfile.write(header + "\n")
        
        # create logging lock
        
        # start sample processing Thread
        self._dict['recording'] = False
        self._dict['connected'] = True
        
        if pipe: self._queue = self._manager.Queue()
        else: self._queue = None
        
        self._spthread = mp.Process(target=_sampleprocesser,args=(self._dict,self._queue,self._loglock))
        self._spthread.daemon = True
        self._spthread.start()
    
    
    def start_recording(self):
        """
        desc:
            Starts writing MP150 samples to the log file.
        """
        
        # signal to the sample processing thread that recording is active
        self._dict['recording'] = True
    
    
    def stop_recording(self):
        """
        desc:
            Stops writing MP150 samples to the log file.
        """
        
        # signal to the sample processing thread that recording stopped
        self._dict['recording'] = False

        # consolidate logged data
        self._loglock.acquire(True)
        self._logfile.flush() # internal buffer to RAM
        os.fsync(self._logfile.fileno()) # RAM file cache to disk
        self._loglock.release()
    
    
    def sample(self):
        """
        desc:
            Returns the most recent sample provided by the MP150.
        
        returns:
            desc:The latest MP150 output values for channels
                (as a list of floats).
            type:numpy.array
        """
        
        return self._newestsample

    
    def log(self, msg):
        """
        desc:
            Writes a message to the log file.
        
        arguments:
            msg:
                desc:The message that is to be written to the log file.
                type:str
        """
        
        # wait for the logging lock to be released, then lock it
        self._loglock.acquire(True)
        
        # write log message, including timestamp
        self._logfile.write("MSG,%d,%s\n" % (self.get_timestamp(), msg))
        
        # release the logging lock
        self._loglock.release()


    def close(self):
        """
        desc:
            Closes the connection to the MP150.
        """
        
        # stop recording
        if self._dict['recording']:
            self.stop_recording()
        # close log file
        self._logfile.close()
        # stop sample processing thread
        self._dict['connected'] = False
        
        # close connection
        try:
            result = mpdev.disconnectMPDev()
        except:
            result = "failed to call disconnectMPDev"
        if check_returncode(result) != "MPSUCCESS":
            raise Exception("Error in libmpdev: failed to close the connection to the MP150: %s" % result)


    def get_timestamp(self):
        """
        desc:
            Returns the time in milliseconds since the connection was opened
        
        returns:
            desc:Time (milliseconds) since connection was opened
            type:int
        """
        
        return int((time.time()-self._dict['start_time']) * 1000)
    
    
def _sampleprocesser(dic,que,loc):
    """
    desc:
        Processes samples while self._recording is True (INTERNAL USE!)
        """
    newestsample = np.zeros(len(dic['channels']))
    newesttime = 0
    
    # run until the connection is closed
    while dic['connected']:
        # get new sample
        try:
            data = np.zeros(12)
            data = (c_double * len(data))(*data)
            result = mpdev.getMostRecentSample(byref(data))
            data = np.array(tuple(data))[dic['channels'] == 1]
        except:
            result = "failed to call getMPBuffer"
            if check_returncode(result) != "MPSUCCESS":
                raise Exception("Error in libmpdev: failed to obtain a sample from the MP150: %s" % result)
        # update newest sample
        if not np.all(data == newestsample):
            newestsample = copy.deepcopy(data)
            newesttime = int((time.time()-dic['start_time']) * 1000)
        # write sample to file
        if dic['recording']:
            # wait for the logging lock to be released, then lock it
            loc.acquire(True)
            # log data
            self._logfile.write("%d," % self._newesttime)
            self._newestsample.tofile(self._logfile,sep=',',format='%.3f')
            self._logfile.write("\n")
            # release the logging lock
            loc.release()
        # if applicable, send data to queue
        if que:
            que.put((newesttime,newestsample))