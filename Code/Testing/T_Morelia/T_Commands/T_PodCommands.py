# local imports
from Morelia.Commands import CommandSet
from Testing.T_Morelia.TestProtocol import RunningTests, TestResult

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

def RunTests(printTests: bool = True) -> tuple[int,int]: 
    """Run all tests on Morelia.Commands.CommandSet.

    Args:
        printTests (bool, optional): Make True to print the test results and messages. Defaults to True.
    
    Returns:
        tuple[int,int]: First item is the number of passed tests. Last item is the total number of tests
    """
    # collect all tests
    tests = {
      '1. Basic instance:\t'    : BuildBasic,
      '2. Add command:\t\t'     : AddCommand,
      '3. Remove command:\t'    : RemoveCommand,
      '4. Restore commands:\t'  : Restore,
      '5. Number from name:\t'  : NumFromName,
      '6. Get argument:\t'      : ArgChar,
      '7. Get return:\t\t'      : RetChar,
      '8. Get binary state:\t'  : IsBin,
      '9. Get description:\t'   : Desc,
      '10. Command exists:\t'   : DoesCmdExt,
      '11. Search:\t\t'         : Search
    }
    return RunningTests.RunTests(tests, 'CommandSet', printTests=printTests)

def BuildBasic() -> TestResult: 
    """Test if calling GetCommands() on a newly initialized command set and check that it gives the basic commands. 

    Returns:
        TestResult: Result of the test. 
    """
    if(CommandSet().GetCommands() == CommandSet.GetBasicCommands()) : 
        return TestResult(True)
    else : 
        return TestResult(False, 'CommandSet initialization does not yeild a basic set.')
    
def AddCommand() -> TestResult :
    """Check if a new command was correctly added to the basic command set. 

    Returns:
        TestResult: Result of the test. 
    """
    # setup new command to add 
    newCmdNum = 999
    newCmd = ['TEST',  (0,),  (0,),  False,  'This is a Test.']
    # create object and add comand 
    cmdset = CommandSet()
    cmdset.AddCommand(newCmdNum, newCmd[0], newCmd[1], newCmd[2], newCmd[3], newCmd[4])
    newCmds = cmdset.GetCommands()
    # check if command was correctly added
    if(newCmdNum not in newCmds) : 
        return TestResult(False, 'Command number entry not added to the set.')
    elif(newCmds[newCmdNum] != newCmd) : 
        return TestResult(False, 'New command information not correctly added to the entry.\n\tExpected: '+str(newCmd)+'\n\tRecieved: '+str(newCmds[newCmdNum]))
    else : 
        return TestResult(True)
    
def RemoveCommand() -> TestResult :
    """Check if a command can be removed from a command set

    Returns:
        TestResult: Result of the test. 
    """
    # remive command zero from basic command set
    cmdset = CommandSet()
    cmdset.RemoveCommand(0)
    # check if command number 0 is in dict 
    if(0 in cmdset.GetCommands()) : 
        return TestResult(False, 'Command was not removed from the set.')
    else :
        return TestResult(True)
    
def Restore() -> TestResult : 
    """Check if the basic commands can be restored after adding and removing a command.

    Returns:
        TestResult: Result of the test. 
    """
    cmdset = CommandSet()
    # remove a command 
    cmdset.RemoveCommand(0)
    if(cmdset.DoesCommandExist(0)) : 
        return TestResult(False, 'Command was not removed from the set.')
    # add a command 
    cmdset.AddCommand(999,'TEST',  (0,),  (0,),  False,  'This is a Test.')
    if(not cmdset.DoesCommandExist(999)) : return TestResult(False, 'Command could not be added to the set.')
    # restore basics, which reverts all changes 
    cmdset.RestoreBasicCommands()
    if(cmdset.GetBasicCommands() != cmdset.GetCommands() ) : 
        return TestResult(False, 'Basic commands could not be restored after removing/adding a command.')
    else : 
        return TestResult(True)
    
def NumFromName() -> TestResult :
    """Check to see if the class can convert a command name to its command number. 

    Returns:
        TestResult: Result of the test. 
    """
    cmdset = CommandSet()
    retrieve = cmdset.CommandNumberFromName('ACK')
    if(0 != retrieve) :
        return TestResult(False, "Retrieved the wrong command number from the name 'ACK'.\n\tExpected: 0\n\tRecieved: "+str(retrieve))
    else : 
        return TestResult(True)
    
def ArgChar() -> TestResult :
    """Check to see if the class can retrieve the argument hex characters given a command number.

    Returns:
        TestResult: Result of the test. 
    """
    cmdset = CommandSet()
    retrieve = cmdset.ArgumentHexChar(0)
    if((0,) != retrieve) : 
        return TestResult(False, "Retrieved the wrong argument hex char from command 0.\n\tExpected: (0,) \n\tRecieved: "+str(retrieve))
    else : 
        return TestResult(True)
    
def RetChar() -> TestResult :
    """Check to see if the class can retrieve the return hex characters given a command number.

    Returns:
        TestResult: Result of the test. 
    """
    cmdset = CommandSet()
    retrieve = cmdset.ReturnHexChar(0)
    if((0,) != retrieve) : 
        return TestResult(False, "Retrieved the wrong return hex char from command 0.\n\tExpected: (0,) \n\tRecieved: "+str(retrieve))
    else : 
        return TestResult(True)   
    
def IsBin() -> TestResult :
    """Check to see if the class can retrieve the binary flag given a command number.

    Returns:
        TestResult: Result of the test. 
    """
    cmdset = CommandSet()
    retrieve = cmdset.IsCommandBinary(0)
    if(False != retrieve) : 
        return TestResult(False, "Retrieved the wrong return hex char from command 0.\n\tExpected: False \n\tRecieved: "+str(retrieve))
    else : 
        return TestResult(True)  
    
def Desc() -> TestResult :
    """Check to see if the class can retrieve the description given a command number.

    Returns:
        TestResult: Result of the test. 
    """
    cmdset = CommandSet()
    retrieve = cmdset.Description(0)
    expected = 'Deprecated in favor of responding with the command number received.'
    if(expected != retrieve) : 
        return TestResult(False, "Retrieved the wrong return hex char from command 0.\n\tExpected: "+str(expected)+"\n\tRecieved: "+str(retrieve))
    else : 
        return TestResult(True)  

def DoesCmdExt() -> TestResult :
    """Check if a command exists in a given command set.

    Returns:
        TestResult: Result of the test. 
    """
    cmdset = CommandSet()
    if(not cmdset.DoesCommandExist(0)) : 
        return TestResult(False, "Could not find an existing command.")
    elif(cmdset.DoesCommandExist(999)) :
        return TestResult(False, "Identifies a command which should not exist in the set.")
    else : 
        return TestResult(True)
    
def Search() -> TestResult : 
    """Check to see if the class can find the command information given the command number and list index.

    Returns:
        TestResult: Result of the test. 
    """
    cmdset = CommandSet()
    # search for command that does exist
    expected = [ 'ACK', (0,), (0,), False,  'Deprecated in favor of responding with the command number received.' ]
    for idx, value in enumerate(expected) : 
        retrieve = cmdset.Search(0, idx=idx)
        if(retrieve != value) : 
            return TestResult(False, "Command information at index "+str(idx)+" could not be found in a search.\n\tExpected: "+str(value)+"\n\tRecieved: "+str(retrieve))
    # search for command that does NOT exist 
    retrieve = cmdset.Search(999)
    expected = False
    if(retrieve != expected) : 
        return TestResult(False, "Command that does not exist was found in a search.")
    # otherwise
    return TestResult(True)