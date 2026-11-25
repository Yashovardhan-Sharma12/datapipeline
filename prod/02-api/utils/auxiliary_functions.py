'''
This file contains functions of general use/applications that are usually shared between the different database
connectors.
'''

import pathlib as pl

def read_query(query: str | pl.Path) -> str:
    '''
    Serves to implement for either strings or Pathlib paths to text files containing queries.
    '''
    match type(query):
        case pl.WindowsPath:
            with open(query, 'r') as f:
                query_txt = f.read()
        case str:
            query_txt = query
    return query_txt
 