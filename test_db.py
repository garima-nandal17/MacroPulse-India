import mysql.connector

try:
    conn = mysql.connector.connect(
        host="localhost",
        user="macropulse",
        password="MacroPulse123!",
        database="macropulse_india"
    )

    print("CONNECTED")
    conn.close()

except Exception as e:
    print(e)