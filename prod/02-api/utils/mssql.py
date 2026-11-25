'''
Module contains a connector that wraps pandas database functionality to simplify day-to-day data transfer
operations between pandas and sql server.
'''

import pathlib as pl
import pandas as pd
import sqlalchemy as sqla
import pyodbc
from dataclasses import dataclass
import utils.auxiliary_functions as aux
import urllib

@dataclass
class Config: # class meant only to hold the configuration details for the databases
    '''
    Configuration dataclass, to keep all the info needed for a DB connection organized.
    '''
    server: str
    db: str
    behavior: str # defines how the system will act when trying to insert data to a target table that already exists
    driver: str = 'ODBC Driver 17 for SQL Server'

    def __post_init__(self):
        if self.behavior not in ['fail', 'replace', 'append']:
            raise ValueError('Behaviour must be either "fail", "replace" or "append".')


class Connector:
    '''
    Provides a simplified interface to exchange information between pandas dataframes and a sql server
    database defined by the config class passed as a parameter in the initialization of this class.
    '''
    def __init__(self, config: Config):
        self.drv: str = config.driver
        self.server: str = config.server
        self.db: str = config.db
        self.behavior: str = config.behavior

        conn_parameters: dict[str, str] = {
            'DRIVER': self.drv,
            'SERVER': self.server,
            'DATABASE': self.db,
            'Trusted_Connection': 'yes',
            'TrustServerCertificate': 'yes'#,
            #'autocommit': 'true'
        }

        conn_string = ';'.join([f'{k}={v}' for k,v in conn_parameters.items()])
        self.engine = sqla.create_engine(f'mssql+pyodbc:///?odbc_connect={urllib.parse.quote_plus(conn_string)}')
        self.sql_server_limit: int = 2100 # sqlserver parameter limit
   
    def pandas2sql(self, df: pd.DataFrame, schema: str, table: str, dtype: dict[str, sqla.types.TypeEngine] | sqla.types.TypeEngine = {}) -> None:
        '''
        Inserts a pandas dataframe into a target schema.table, it creates the table if it doesn't
        exist in the first place.
        '''
        df.to_sql(
            table,
            self.engine,
            index = False,
            schema = schema,
            if_exists = self.behavior,
            method = 'multi',
            dtype = dtype,
            chunksize = int((self.sql_server_limit / len(df.columns)) - 10) # chunksize is calculated based on the sql server parameter limit. The nearest you get to it without exceeding it the faster the insert
        )

    def sql2pandas(self, query: str | pl.Path) -> pd.DataFrame:
        '''Returns the result from a query as a pandas dataframe.'''
        return pd.read_sql(
            aux.read_query(query), self.engine)

    def execute_sql(self, query: str | pl.Path | list[str | pl.Path]) -> None:
        '''
        Executes a single or multiple sql statements wrapped in one transaction with rollback for all at once on fail.
        '''
        lst_queries = [query] if (type(query) != list) else query

        with pyodbc.connect(
            f'Driver={self.drv};'
            f'Server={self.server};'
            f'Database={self.db};'
            f'Trusted_Connection=yes;'
            f'TrustServerCertificate=yes',
            autocommit=False
        ) as pyodbc_conn:
            with pyodbc_conn.cursor() as cursor:
                try:
                    for query in lst_queries:
                        cursor.execute(aux.read_query(query))
                except:
                    cursor.rollback()
                    raise
                cursor.commit()



#%%
# USAGE EXAMPLE
if __name__ == '__main__':
    conn = Connector(Config(server='tpc003499.tgrc.tesco.org', db='Staging', behavior='append'))
    df = conn.sql2pandas('SELECT TOP 10 * FROM RAw.OneCECCase.Case')