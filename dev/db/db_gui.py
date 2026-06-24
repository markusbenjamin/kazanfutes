import duckdb

con = duckdb.connect("store/observations.duckdb")

con.execute("INSTALL ui;")
con.execute("LOAD ui;")
con.execute("CALL start_ui();")

input("DuckDB UI is running. Press Enter to stop...")