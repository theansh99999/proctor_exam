"""

Test Module: Group Management

Tests group creation, member addition, and group operations

"""



import sys

sys.path.insert(0, '..')



from fastapi.testclient import TestClient

from main import app

import models

from database import engine, SessionLocal

import auth



client = TestClient(app)



def test_group_creation():

    """Test group creation by teacher"""

    try:

        models.Base.metadata.drop_all(bind=engine)

        models.Base.metadata.create_all(bind=engine)



        db = SessionLocal()

        # Create teacher

        teacher = models.User(

            email="teacher@example.com",

            password_hash=auth.get_password_hash("pass123"),

            name="Teacher One",

            role="teacher"

        )

        db.add(teacher)

        db.commit()



        # Create group

        group = models.Group(

            name="Class A",

            teacher_id=teacher.id

        )

        db.add(group)

        db.commit()



        assert group.id is not None, "Group ID not assigned"

        assert group.name == "Class A"

        assert group.teacher_id == teacher.id



        db.close()

        return True, "✓ Group creation works"

    except Exception as e:

        return False, f"✗ Group creation failed: {str(e)}"



def test_add_group_member():

    """Test adding student to group"""

    try:

        db = SessionLocal()



        # Create teacher and group

        teacher = models.User(

            email="teacher2@example.com",

            password_hash=auth.get_password_hash("pass123"),

            name="Teacher Two",

            role="teacher"

        )

        db.add(teacher)

        db.commit()



        group = models.Group(name="Class B", teacher_id=teacher.id)

        db.add(group)

        db.commit()



        # Add student to group

        member = models.GroupMember(

            group_id=group.id,

            student_email="student1@example.com"

        )

        db.add(member)

        db.commit()



        # Verify

        members = db.query(models.GroupMember).filter(models.GroupMember.group_id == group.id).all()

        assert len(members) == 1, "Member not added"

        assert members[0].student_email == "student1@example.com"



        db.close()

        return True, "✓ Group member addition works"

    except Exception as e:

        return False, f"✗ Add group member failed: {str(e)}"



def test_group_member_removal():

    """Test removing student from group"""

    try:

        db = SessionLocal()



        teacher = models.User(

            email="teacher3@example.com",

            password_hash=auth.get_password_hash("pass123"),

            name="Teacher Three",

            role="teacher"

        )

        db.add(teacher)

        db.commit()



        group = models.Group(name="Class C", teacher_id=teacher.id)

        db.add(group)

        db.commit()



        member = models.GroupMember(group_id=group.id, student_email="student2@example.com")

        db.add(member)

        db.commit()



        # Remove member

        db.delete(member)

        db.commit()



        # Verify removal

        members = db.query(models.GroupMember).filter(models.GroupMember.group_id == group.id).all()

        assert len(members) == 0, "Member not removed"



        db.close()

        return True, "✓ Group member removal works"

    except Exception as e:

        return False, f"✗ Remove group member failed: {str(e)}"



def test_multiple_groups():

    """Test teacher with multiple groups"""

    try:

        db = SessionLocal()



        teacher = models.User(

            email="teacher4@example.com",

            password_hash=auth.get_password_hash("pass123"),

            name="Teacher Four",

            role="teacher"

        )

        db.add(teacher)

        db.commit()



        # Create multiple groups

        for i in range(3):

            group = models.Group(name=f"Class {chr(65+i)}", teacher_id=teacher.id)

            db.add(group)

        db.commit()



        # Verify

        groups = db.query(models.Group).filter(models.Group.teacher_id == teacher.id).all()

        assert len(groups) == 3, f"Expected 3 groups, got {len(groups)}"



        db.close()

        return True, "✓ Multiple groups work"

    except Exception as e:

        return False, f"✗ Multiple groups failed: {str(e)}"



def run_all_group_tests():

    """Run all group management tests"""

    print("\n" + "="*60)

    print("👥 GROUP MANAGEMENT TESTS")

    print("="*60)



    tests = [

        ("Group Creation", test_group_creation),

        ("Add Group Member", test_add_group_member),

        ("Remove Group Member", test_group_member_removal),

        ("Multiple Groups", test_multiple_groups),

    ]



    results = []

    for test_name, test_func in tests:

        passed, message = test_func()

        results.append((test_name, passed))

        status_icon = "✓" if passed else "✗"

        print(f"{status_icon} {test_name:30} {message}")



    passed_count = sum(1 for _, p in results if p)

    return passed_count, len(results)



if __name__ == "__main__":

    run_all_group_tests()
