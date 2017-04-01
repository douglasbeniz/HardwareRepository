import logging
import weakref
import copy
import gevent

# LNLS
#from . import saferef
#from saferef import *
import saferef
#from . import Poller
#from Poller import *
import Poller
#from .CommandContainer import CommandObject, ChannelObject
from CommandContainer import CommandObject, ChannelObject

try:
    import epics
except ImportError:
    logging.getLogger('HWR').warning("EPICS support not available.")


class EpicsCommand(CommandObject):
    def __init__(self, name, pv_name, username = None, args=None, **kwargs):
        CommandObject.__init__(self, name, username, **kwargs)
        
        self.pv_name = pv_name
        self.read_as_str = kwargs.get("read_as_str", False)
        self.auto_monitor = kwargs.get("auto_monitor", True)
        self.pollers = {}
        self.__valueChangedCallbackRef = None
        self.__timeoutCallbackRef = None

        if args is None:
            self.arglist = ()
        else:
            # not very nice...
            args = str(args)
            if not args.endswith(","):
              args+=","
            self.arglist = eval("("+args+")")
 
        if len(self.arglist) > 1:
            logging.getLogger('HWR').error("EpicsCommand: ftm only scalar arguments are supported.")
            return

        logging.getLogger('HWR').debug("EpicsCommand: creating pv %s: read_as_str = %s", self.pv_name, self.read_as_str)

        # LNLS
        #self.pv = epics.PV(pv_name, auto_monitor = True)
        self.pv = epics.PV(pv_name, auto_monitor = self.auto_monitor)
        self.pv_connected = self.pv.connect()

        # LNLS
        if (self.pv_connected):
            self.valueChanged(self.pv.get(as_string = self.read_as_str))
        else:
            logging.getLogger('HWR').error("EpicsCommand: Error connecting to pv %s.", self.pv_name)

       
    def __call__(self, *args, **kwargs):
        self.emit('commandBeginWaitReply', (str(self.name()), ))
       
        if len(args) > 0 and len(self.arglist) > 0:
            # arguments given both given in command call _AND_ in the xml file
            logging.getLogger("HWR").error("%s: cannot execute command with arguments when 'args' is defined from XML", str(self.name()))
            self.emit('commandFailed', (-1, str(self.name()), ))
            return
        elif len(args) == 0 and len(self.arglist) > 0:
            # no argument given in the command call but inside the xml file -> use the default argument from the xml file
            args = self.arglist 

        # LNLS
        #if self.pv is not None and self.pv_connected:
        if self.pv is not None:
            if len(args) == 0:
                # no arguments available -> get the pv's current value
                try:
                    ret = self.pv.get(as_string = self.read_as_str, timeout=0.2)
                    # LNLS
                    # If a try to get info return a None object, retry once more...
                    if (ret is None):
                        ret = self.reconnect()
                except TypeError:
                    # LNLS
                    # When a cached info is lost internally Epics return a TypeError: NoneType...
                    ret = self.reconnect()

                    if (ret is not None):
                        self.emit('commandReplyArrived', (ret, str(self.name())))
                        return ret
                except:
                    logging.getLogger('HWR').error("%s: an error occured when calling Epics command %s", str(self.name()), self.pv_name)
                else:
                    self.emit('commandReplyArrived', (ret, str(self.name())))
                    return ret
            else:
                # use the given argument to change the pv's value
                try:
                    # LNLS
                    #self.pv.put(args[0], wait = True)
                    self.pv.put(args[0], wait = args[1])
                except:
                    logging.getLogger('HWR').error("%s: an error occured when calling Epics command %s", str(self.name()), self.pv_name)
                else:
                    self.emit('commandReplyArrived', (0, str(self.name())))
                    return 0
        self.emit('commandFailed', (-1, str(self.name()), ))


    def valueChanged(self, value):
        try:
            # LNLS
            #callback = self.__valueChangedCallbackRef()
            callback = self.__valueChangedCallbackRef(value)
        except:
            pass
        else:
            if callback is not None:
                callback(value)

    def onPollingError(self, exception, poller_id):
        print("onPollingError")
        # try to reconnect the pv
        self.pv.connect()

        poller = Poller.get_poller(poller_id)
        if poller is not None:
            try:
                poller.restart(1000)
            except:
                pass

    def getPvValue(self):
        # wrapper function to pv.get() in order to supply additional named parameter
        return self.pv.get(as_string = self.read_as_str)

    def poll(self, pollingTime=500, argumentsList=(), valueChangedCallback=None, timeoutCallback=None, direct=True, compare=True):
        # LNLS
        #self.__valueChangedCallbackRef = saferef.safe_ref(valueChangedCallback)
        self.__valueChangedCallbackRef = valueChangedCallback

        # store the call to get as a function object
        # poll_cmd = self.pv.get
        poll_cmd = self.getPvValue

        Poller.poll(poll_cmd, copy.deepcopy(argumentsList), pollingTime, self.valueChanged, self.onPollingError, compare)

    def stopPolling(self):
        pass

    def abort(self):
        pass

    def isConnected(self):
        return self.pv_connected

    # LNLS
    def reconnect(self):
        # Clear Epics cache
        epics.ca._cache.clear()
        #epics.ca._put_done.clear()

        # Reconnect PV
        self.pv = epics.PV(self.pv_name, auto_monitor = self.auto_monitor)
        self.pv_connected = self.pv.connect()

        # Return the result of get()
        return self.pv.get(as_string = self.read_as_str, timeout=0.2)


class EpicsChannel(ChannelObject):
    """Emulation of a 'Epics channel' = an Epics command + polling"""
    def __init__(self, name, command, username = None, polling=None, args=None, **kwargs):
        ChannelObject.__init__(self, name, username, **kwargs)

        self.command = EpicsCommand(name+"_internalCmd", command, username, args, **kwargs)
        
        try:
            self.polling = int(polling)
        except:
            self.polling = None
        else:
            self.command.poll(self.polling, self.command.arglist, self.valueChanged)

    def valueChanged(self, value):
        self.emit("update", value)

    def getValue(self):
        return self.command()

    # LNLS
    def setValue(self, value, wait=False):
        self.command(value, wait)
 
    def isConnected(self):
        return self.command.isConnected()

    def reconnect(self):
        self.command.reconnect()
