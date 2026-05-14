"""
V031 — Add '2fa_attempt' to error_log.event_type enum
"""


def run(cnx):
    cur = cnx.cursor()
    try:
        cur.execute(
            """ALTER TABLE error_log
               MODIFY event_type ENUM (
                   'server_call',
                   'sql_error',
                   'unknown_error',
                   'unauthorized_access',
                   'login_attempt',
                   '2fa_attempt'
               ) NOT NULL"""
        )
        cnx.commit()
        print("    V031: error_log.event_type enum extended with '2fa_attempt'")
    finally:
        cur.close()
