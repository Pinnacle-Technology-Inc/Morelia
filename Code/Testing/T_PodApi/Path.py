
""" This Python script contains functions to add the Python POD API project modules \
    directory path to your system. This allows the computer to find and use the API \
    modules in other Python scripts.
"""

def AddAPIpath() : 
    """Add directory path <...>\Python-POD-API\Code\PodApi to code 
    """
    import sys, os
    # get current path, and split into list surrounding 'Python-POD-API'
    aroundApi = os.path.abspath('.').split('Python-POD-API')
    # build directory path 
    apiPath = aroundApi[0] + 'Python-POD-API'
    # check if the 'Python-POD-API' has any trailing text before any subdirectories
    if(len(aroundApi) > 1 and (not aroundApi[1].startswith('\\'))): 
        # add trailing text to the api path
        apiPath += aroundApi[1].split('\\')[0]
    # add api path to system path
    sys.path.insert(0, os.path.join( apiPath, 'Code') )
    