
import sys
import os
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

base_dir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(base_dir, 'data', 'keg_tasks.db')
backup_path = os.path.join(base_dir, 'backups', 'keg_tasks_backup_20251118_170333.db')

def restore_from_backup():

    if not os.path.exists(backup_path):
        print(f"[ERROR] Rezervnaya kopiya ne naidena: {backup_path}")
        return False

    current_backup = db_path + '.before_restore'
    if os.path.exists(db_path):
        shutil.copy2(db_path, current_backup)
        print(f"[OK] Sozdana rezervnaya kopiya tekushchei BD: {current_backup}")

    shutil.copy2(backup_path, db_path)
    print(f"[OK] BD vosstanovlena iz rezervnoi kopii: {backup_path}")
    print(f"[OK] Vosstanovlenie zaversheno!")
    return True

if __name__ == '__main__':
    restore_from_backup()
