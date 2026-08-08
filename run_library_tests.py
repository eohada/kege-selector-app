import sys
import os

sys.stdout.reconfigure(encoding='utf-8')

from tests.v2.test_library_hub import (
    client,
    test_1_library_get_as_teacher,
    test_2_upload_material_api,
    test_3_download_material,
    test_4_delete_material_api,
    test_5_student_access_redirect
)

c_gen = client()
c = next(c_gen)

print("Running QA Test Suite for Library Hub V2:")

try:
    test_1_library_get_as_teacher(c)
    print("  ✅ Test 1 PASS: GET /library as teacher returns 200 OK")

    test_2_upload_material_api(c)
    print("  ✅ Test 2 PASS: POST /api/teacher/materials/upload uploads file and creates DB record")

    test_3_download_material(c)
    print("  ✅ Test 3 PASS: GET /materials/download/<id> serves file")

    test_4_delete_material_api(c)
    print("  ✅ Test 4 PASS: DELETE /api/teacher/materials/<id> removes DB record and file on disk")

    test_5_student_access_redirect(c)
    print("  ✅ Test 5 PASS: Student access to /library returns 302 redirect to /dashboard")

    print("\nALL 5 QA TESTS PASSED SUCCESSFULLY! (100% PASS)")
except Exception as e:
    import traceback
    print("  ❌ TEST FAILED:", e)
    traceback.print_exc()
finally:
    try:
        next(c_gen)
    except StopIteration:
        pass
