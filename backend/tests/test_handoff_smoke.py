"""The handoff command must test real local HTTP and leave no account data."""
import json
import importlib.util
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def load_checker():
    spec = importlib.util.spec_from_file_location('handoff_checker', ROOT / 'scripts/handoff/verify_backend.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_checker(root, tmp_path):
    runtime = tmp_path / 'temporary-runtime'
    runtime.mkdir()
    report = tmp_path / 'report.json'
    existing = tmp_path / 'existing.db'
    existing.write_bytes(b'do not open this database')
    collector = tmp_path / 'existing-collector'
    env = {
        **os.environ, 'TMPDIR': str(runtime), 'TEMP': str(runtime), 'TMP': str(runtime),
        'CAMPUS_DATABASE_URL': f'sqlite:///{existing}',
        'CAMPUS_COLLECTOR_DATA_DIR': str(collector),
        'CAMPUS_COOKIE_SECURE': 'invalid-inherited-setting',
        'CAMPUS_ALLOWED_ORIGINS': 'invalid-inherited-setting',
    }
    result = subprocess.run(
        [sys.executable, str(root / 'scripts/handoff/verify_backend.py'), '--report', str(report)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
    )
    assert existing.read_bytes() == b'do not open this database'
    assert not collector.exists()
    assert list(runtime.iterdir()) == [], 'Temporary account database was not removed'
    if report.exists():
        data = json.loads(report.read_text())
        with socket.socket() as connection:
            connection.settimeout(1)
            assert connection.connect_ex(('127.0.0.1', data['execution']['port'])) != 0
    return result, report


def test_handoff_command_checks_http_restart_isolation_and_redacts_report(tmp_path):
    # Missing checks, stale installed code, or leaked process/data must fail this test.
    result, report_path = run_checker(ROOT, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(report_path.read_text())
    assert report['status'] == 'passed'
    assert report['source_kind'] == 'synthetic_runtime'
    checks = {item['name']: item['status'] for item in report['checks']}
    required = {
        'init_database', 'health_live', 'health_ready', 'auth_register', 'auth_session',
        'auth_refresh', 'auth_login', 'auth_logout_204', 'logout_session_invalid', 'logout_cookie_revoked',
        'catalog_schools', 'catalog_colleges', 'catalog_college_majors',
        'catalog_school_majors', 'catalog_grades',
        *(f'catalog_preferences_{kind}' for kind in ('course', 'skill', 'goal', 'interest')),
        'profile_empty_wrapped', 'profile_saved_wrapped', 'profile_reread',
        'profile_admission_year_omitted', 'profile_admission_year_cleared',
        'preferences_saved', 'preferences_reread', 'independent_versions',
        'profile_missing_csrf_403', 'preferences_missing_csrf_403',
        'profile_missing_body_version_422', 'preferences_missing_body_version_422',
        'profile_idempotent_replay', 'preferences_idempotent_replay',
        'profile_stale_version_409', 'preferences_stale_version_409',
        'second_session_independent', 'second_session_persisted_data',
        'restart_cookie_recovery', 'other_account_isolated', 'logout_other_session_survives',
        'planned_feed_404', 'planned_detail_404', 'planned_follows_404',
        'planned_follow_write_404', 'planned_coverage_404',
    }
    assert required <= checks.keys()
    assert set(checks.values()) == {'passed'}
    assert report['summary'] == {'passed': len(checks), 'failed': 0, 'total': len(checks)}
    assert report['execution']['server_starts'] == 2
    assert report['execution']['database'] == 'temporary_file_sqlite'
    assert report['cleanup'] == {'server_stopped': True, 'temporary_data_removed': True}
    samples = report['response_samples']
    assert samples['profile']['completed'] is True
    assert samples['preferences']['version'] == 1
    assert samples['preferences']['skill_ids']
    assert samples['profile_missing_body_version']['error']['code'] == 'validation_error'
    assert samples['profile_missing_csrf']['error']['code'] == 'csrf_invalid'
    exposed = report_path.read_text() + result.stdout + result.stderr
    for secret in ('csrf_token', 'campus_session', 'Set-Cookie', 'password', 'smoke-primary@example.com'):
        assert secret not in exposed


def test_handoff_failure_uses_selected_checkout_and_cleans_running_server(tmp_path):
    checkout = tmp_path / 'incomplete-checkout'
    for relative in ('backend/src', 'backend/migrations', 'notice_classifier/campus_notice', 'scripts/handoff'):
        source = ROOT / relative
        if source.exists():
            shutil.copytree(source, checkout / relative, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    # The original editable install has this file. A missing delivery file must fail.
    (checkout / 'backend/src/campus_backend/catalog/data/preferences.json').unlink()
    result, report_path = run_checker(checkout, tmp_path)
    assert result.returncode == 1
    report = json.loads(report_path.read_text())
    assert report['status'] == 'failed'
    assert report['summary']['failed'] == 1
    assert report['execution']['server_starts'] == 1
    assert report['cleanup'] == {'server_stopped': True, 'temporary_data_removed': True}
    assert report['checks'][-1]['name'] == 'catalog_preferences_course'
    assert report['checks'][-1]['status'] == 'failed'
    assert 'Traceback' not in result.stdout + result.stderr


def test_handoff_cleanup_failure_cannot_report_success(tmp_path, monkeypatch):
    checker = load_checker()
    report_path = tmp_path / 'report.json'

    class CleanupFailure:
        def __init__(self, report, directory):
            self.report, self.directory = report, directory
            self.current, self.process = 'cleanup', object()

        def run(self):
            self.report['checks'].append({'name': 'http_check', 'status': 'passed'})

        def stop(self):
            raise OSError('Simulated process cleanup failure')

    monkeypatch.setattr(checker, 'Smoke', CleanupFailure)
    monkeypatch.setattr(checker.signal, 'signal', lambda *args: None)
    monkeypatch.setattr(sys, 'argv', ['verify_backend.py', '--report', str(report_path)])
    assert checker.main() == 1
    report = json.loads(report_path.read_text())
    assert report['status'] == 'failed'
    assert report['summary']['failed'] == 1
    assert report['cleanup']['server_stopped'] is False


def test_handoff_version_distinguishes_repository_dirty_tree_and_nested_archive(tmp_path, monkeypatch):
    checker = load_checker()
    repository = tmp_path / 'repository'
    subprocess.run(['git', 'init', str(repository)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(repository), '-c', 'user.name=Handoff Test',
                    '-c', 'user.email=handoff@example.com', '-c', 'commit.gpgsign=false',
                    '-c', f'core.hooksPath={tmp_path / "no-hooks"}',
                    'commit', '--allow-empty', '-m', 'Synthetic test repository'],
                   check=True, capture_output=True)
    expected = subprocess.check_output(['git', '-C', str(repository), 'rev-parse', 'HEAD'], text=True).strip()
    monkeypatch.setattr(checker, 'ROOT', repository)
    assert checker.project_metadata() == {'project_sha': expected, 'project_dirty': False}
    (repository / 'uncommitted.txt').write_text('not part of the commit')
    assert checker.project_metadata() == {'project_sha': expected, 'project_dirty': True}
    archive = repository / 'archive'
    archive.mkdir()
    monkeypatch.setattr(checker, 'ROOT', archive)
    assert checker.project_metadata() == {'project_sha': None, 'project_dirty': None}
