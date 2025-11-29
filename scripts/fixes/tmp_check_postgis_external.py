import psycopg2
import sys

conn_str = "postgres://postgres:eAefDEdEdf6fFEfef3BcADce2E3BgbFb@switchback.proxy.rlwy.net:16477/railway"
try:
    conn = psycopg2.connect(conn_str)
    cur = conn.cursor()
    try:
        cur.execute("SELECT PostGIS_Version();")
        v = cur.fetchone()
        print("PostGIS_Version:", v[0] if v else None)
    except Exception as e:
        print("PostGIS version query failed:", e)
    try:
        cur.execute("SELECT postgis_full_version();")
        v = cur.fetchone()
        print("postgis_full_version:", v[0][:120] + '...' if v and v[0] else None)
    except Exception as e:
        print("postgis_full_version failed:", e)
    cur.close()
    conn.close()
except Exception as e:
    print("Connection failed:", e)
    sys.exit(2)
print("DONE")
