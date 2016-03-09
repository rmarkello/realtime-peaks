#!/usr/bin/env python

import os
import time
import copy
import numpy as np
import multiprocessing as mp
import logging
import time
import keypress
from libmpdev_v2 import MP150
import scipy.signal

class RTP(MP150):
    
    def __init__(self, logfile='default', samplerate=200, channels=[1,2,3]):
        MP150.__init__(self, logfile, samplerate, channels)
        
        self._dict['peaklog'] = "%s_peak_data.csv" % (logfile)
        self._peak_queue = self._manager.Queue()
                
        self._peak_process = mp.Process(target=_peak_finder,args=(self._dict,self._sample_queue,self._peak_queue))
        self._peak_process.daemon = True
        
        self._peak_log_process = mp.Process(target=_peak_log,args=(self._dict,self._peak_queue))
        self._peak_log_process.daemon = True
        
        
    def start(self):
        self.start_recording()
        self._start_pipe()
        
        self._peak_process.start()
        self._peak_log_process.start()
    
        
    def stop(self):
        self._stop_pipe()
        self.close()
        

def _peak_finder(dic,que_in,que_log):
    last_bunch = np.empty(0)
    peakind_log = np.empty(0)
    
    print "Ready to find peaks..."
    
    while True:
        i = que_in.get()
        if i == 'kill': break
        else:
            last_bunch = np.hstack((last_bunch,i[1]))
            peakind = scipy.signal.argrelmax(last_bunch,order=25)[0]
            
            if peakind.size > peakind_log.size:
                peakind_log = peakind            
                que_log.put(i[0:2])
                keypress.PressKey(0x50)
                keypress.ReleaseKey(0x50)
    
    que_log.put('kill')


def _peak_log(dic,que):
    f = open(dic['peaklog'],'a+')
    
    while True:
        i = que.get()
        if i == 'kill': break
        else:
            logt, signal = i
            f.write('%s,%s\n' % (logt, str(signal).strip('()[],')))
            f.flush()

    f.close()
    

if __name__ == '__main__':
    #mp.log_to_stderr(logging.DEBUG)
    r = RTP(logfile='test',channels=[1,2,3])
    r.start()
    time.sleep(10)
    r.stop()
    print "Done!"