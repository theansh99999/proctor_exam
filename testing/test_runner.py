"""

Test Runner

A central script that runs all testing modules and aggregates results into a rich HTML report.

"""

import sys

import os

import time



sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))



from testing.test_db import cleanup_test_db

from testing.test_auth import get_auth_tests

from testing.teacher.test_groups import get_teacher_group_tests

from testing.teacher.test_exams import get_teacher_exam_tests

from testing.student.test_dashboard import get_student_dashboard_tests

from testing.student.test_exams import get_student_exam_tests

from testing.test_security import get_security_tests



def run_all_tests_and_get_report():

    print("Running all tests...")



    categories = [

        ("🔐 Security Remediation", get_security_tests()),

        ("Authentication & Security", get_auth_tests()),

        ("Teacher: Groups", get_teacher_group_tests()),

        ("Teacher: Exams", get_teacher_exam_tests()),

        ("Student: Dashboard", get_student_dashboard_tests()),

        ("Student: Exams", get_student_exam_tests()),

    ]



    total_tests = 0

    total_passed = 0

    results_html = ""



    start_time = time.time()



    for category_name, tests in categories:

        results_html += f"""

        <div class="category">

            <h2>{category_name}</h2>

            <div class="test-grid">

        """

        for test_name, test_func in tests:

            total_tests += 1

            passed, msg = test_func()

            if passed: total_passed += 1



            status_class = "passed" if passed else "failed"

            icon = "✅" if passed else "❌"



            results_html += f"""

                <div class="test-card {status_class}">

                    <div class="test-header">

                        <span class="icon">{icon}</span>

                        <span class="name">{test_name}</span>

                    </div>

                    <div class="message">{msg}</div>

                </div>

            """

        results_html += "</div></div>"



    time_taken = round(time.time() - start_time, 2)

    pass_rate = round((total_passed / total_tests) * 100) if total_tests > 0 else 0



    cleanup_test_db()



    html_page = f"""

    <!DOCTYPE html>

    <html lang="en">

    <head>

        <meta charset="UTF-8">

        <meta name="viewport" content="width=device-width, initial-scale=1.0">

        <title>System Diagnostic Report</title>

        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">

        <style>

            :root {{

                --bg: #0f111a;

                --surface: #1e2130;

                --text: #e2e8f0;

                --text-muted: #94a3b8;

                --success: #10b981;

                --success-bg: rgba(16, 185, 129, 0.1);

                --danger: #ef4444;

                --danger-bg: rgba(239, 68, 68, 0.1);

                --accent: #3b82f6;

            }}

            body {{

                font-family: 'Inter', sans-serif;

                background-color: var(--bg);

                color: var(--text);

                margin: 0;

                padding: 40px 20px;

                line-height: 1.5;

            }}

            .container {{

                max-width: 1000px;

                margin: 0 auto;

            }}

            header {{

                text-align: center;

                margin-bottom: 40px;

            }}

            h1 {{

                font-size: 2.5rem;

                margin: 0 0 10px 0;

                background: linear-gradient(to right, #3b82f6, #8b5cf6);

                -webkit-background-clip: text;

                -webkit-text-fill-color: transparent;

            }}

            .stats-row {{

                display: flex;

                gap: 20px;

                justify-content: center;

                margin-bottom: 40px;

            }}

            .stat-box {{

                background: var(--surface);

                padding: 20px 30px;

                border-radius: 12px;

                text-align: center;

                box-shadow: 0 4px 6px rgba(0,0,0,0.1);

                border: 1px solid rgba(255,255,255,0.05);

            }}

            .stat-value {{

                font-size: 2rem;

                font-weight: 700;

                margin-bottom: 5px;

            }}

            .stat-label {{

                color: var(--text-muted);

                font-size: 0.9rem;

                text-transform: uppercase;

                letter-spacing: 1px;

            }}

            .category {{

                margin-bottom: 40px;

            }}

            .category h2 {{

                font-size: 1.5rem;

                border-bottom: 2px solid var(--surface);

                padding-bottom: 10px;

                margin-bottom: 20px;

            }}

            .test-grid {{

                display: grid;

                grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));

                gap: 20px;

            }}

            .test-card {{

                background: var(--surface);

                border-radius: 10px;

                padding: 20px;

                border: 1px solid rgba(255,255,255,0.05);

                transition: transform 0.2s, box-shadow 0.2s;

            }}

            .test-card:hover {{

                transform: translateY(-2px);

                box-shadow: 0 8px 12px rgba(0,0,0,0.2);

            }}

            .test-card.passed {{

                border-left: 4px solid var(--success);

                background: linear-gradient(to right, var(--success-bg), transparent);

            }}

            .test-card.failed {{

                border-left: 4px solid var(--danger);

                background: linear-gradient(to right, var(--danger-bg), transparent);

            }}

            .test-header {{

                display: flex;

                align-items: center;

                gap: 10px;

                margin-bottom: 10px;

                font-weight: 600;

                font-size: 1.1rem;

            }}

            .message {{

                font-size: 0.9rem;

                color: var(--text-muted);

            }}



            @keyframes pulse {{

                0% {{ opacity: 1; }}

                50% {{ opacity: 0.7; }}

                100% {{ opacity: 1; }}

            }}

            .stat-box.success-rate {{

                position: relative;

                overflow: hidden;

            }}

            .stat-box.success-rate::before {{

                content: '';

                position: absolute;

                top: 0; left: 0; right: 0; bottom: 0;

                background: {f"var(--success-bg)" if pass_rate == 100 else f"var(--danger-bg)"};

                z-index: 0;

            }}

            .stat-box.success-rate > * {{

                position: relative;

                z-index: 1;

            }}

        </style>

    </head>

    <body>

        <div class="container">

            <header>

                <h1>System Functionality Report</h1>

                <p style="color: var(--text-muted);">Real-time diagnostic analysis of the Exam Proctoring Platform</p>

            </header>



            <div class="stats-row">

                <div class="stat-box success-rate">

                    <div class="stat-value" style="color: {f"var(--success)" if pass_rate == 100 else f"var(--danger)"}">{pass_rate}%</div>

                    <div class="stat-label">Pass Rate</div>

                </div>

                <div class="stat-box">

                    <div class="stat-value">{total_passed}/{total_tests}</div>

                    <div class="stat-label">Tests Passed</div>

                </div>

                <div class="stat-box">

                    <div class="stat-value">{time_taken}s</div>

                    <div class="stat-label">Execution Time</div>

                </div>

            </div>



            {results_html}

        </div>

    </body>

    </html>

    """

    return html_page



if __name__ == "__main__":

    with open("report.html", "w", encoding="utf-8") as f:

        f.write(run_all_tests_and_get_report())

    print("Report saved as report.html")
