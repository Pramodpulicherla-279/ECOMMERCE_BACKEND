import mysql.connector
from mysql.connector import Error

def get_db1():
    try:
        connection = mysql.connector.connect(
            host='127.0.0.1',
            user='root',
            password='Pramod@23057',
            database='Ecommerce_DB'
        )
        if connection.is_connected():
            print("Connected to MySQL database")
            return connection
    except Error as e:
        print(f"Error while connecting to MySQL: {e}")
        return None

def execute_query(query, params=None):
    connection = get_db1()
    if connection:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(query, params)
            result = cursor.fetchall()
            connection.commit()
            return result
        except Error as e:
            print(f"Error executing query: {e}")
            return None
        finally:
            cursor.close()
            connection.close()
    return None