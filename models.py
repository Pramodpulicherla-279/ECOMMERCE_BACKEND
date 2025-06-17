import mysql.connector
import urllib.parse

# URL-encode the password
password = urllib.parse.quote_plus('Pramod@23057')

# Establish the database connection
connection = mysql.connector.connect(
    host="127.0.0.1",
    user="root",
    password=password,
    database="Ecommerce_DB"
)

cursor = connection.cursor()

# SQL query to create the products table
create_table_query = """
CREATE TABLE IF NOT EXISTS products (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    price FLOAT NOT NULL,
    stock INT NOT NULL,
    category VARCHAR(255),
    imageUrls JSON,
    mainImageUrl VARCHAR(255),
    demanded BOOLEAN,
    keywords VARCHAR(255)
)
"""

# Execute the create table query
cursor.execute(create_table_query)
connection.commit()

# Close the cursor and connection
cursor.close()
connection.close()