"""t261009-13 UT：repair hatch slice 1（唯一快修口：授权/记录/票路径闸/认证债）。

被测面 = server/tools/ticket.py 的 _repair_hatch / _hatch_debts 及其纯函数
（store 路径、id 铸造、fail-closed 读、flock 追加、who 归一比对、expires 解析、
破损核对、修订集、票路径闸、覆盖清债、唯一口断言）。全走临时 store 根
（SANDBAR_PROJECTS_DIR 注入，shared.perkey_projects_root 的测试钉面），
零 Temporal、零集成入口。
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'server' / 'tools'))

import importlib.util
_spec = importlib.util.spec_from_file_location('_tk_t261009_13', REPO / 'server' / 'tools' / 'ticket.py')
tk = importlib.util.module_from_spec(_spec)
sys.modules['_tk_t261009_13'] = _tk_t261009_13 = tk
_spec.loader.exec_module(tk)


class HatchTestBase(unittest.TestCase):
    """每个用例一份独立临时 store 根 + 独立 cwd（票路径闸按 cwd 判）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store_root = Path(self._tmp.name) / 'projects'
        self._old_projects_env = os.environ.get('SANDBAR_PROJECTS_DIR')
        os.environ['SANDBAR_PROJECTS_DIR'] = str(self.store_root)
        self._old_cwd = os.getcwd()
        os.chdir(self._tmp.name)  # 仓外 cwd：不触票路径闸
        self.ok = {'project': 'sandbar', 'by': '宿主（sandbar 项目会话）',
                   'breakage': {'description': 'lane dispatch wedged on missing venv'},
                   'revisions': ['abc1234', 'def5678'],
                   'expires': int(time.time()) + 3600}

    def tearDown(self):
        os.chdir(self._old_cwd)
        if self._old_projects_env is None:
            os.environ.pop('SANDBAR_PROJECTS_DIR', None)
        else:
            os.environ['SANDBAR_PROJECTS_DIR'] = self._old_projects_env
        self._tmp.cleanup()

    def hatch(self, **over):
        args = dict(self.ok)
        for k, v in over.items():
            if v is None:
                args.pop(k, None)
            else:
                args[k] = v
        return tk.run({'op': 'repair_hatch', **args})

    def records_file(self):
        return self.store_root / 'sandbar' / 'hatch' / 'hatch_records.jsonl'

    def read_lines(self):
        return self.records_file().read_text(encoding='utf-8').splitlines()


class TestHappyPathAndStore(HatchTestBase):
    def test_record_appended_with_all_fields_and_moment(self):
        out = self.hatch()
        lines = self.read_lines()
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        self.assertEqual(rec['v'], 'hatch-authorisation-v1')
        self.assertEqual(rec['id'], out['hatch_id'])
        self.assertEqual(rec['by'], self.ok['by'])
        self.assertEqual(rec['revisions'], ['abc1234', 'def5678'])
        self.assertEqual(rec['expires'], self.ok['expires'])
        self.assertEqual(rec['breakage'], {'description': self.ok['breakage']['description']})
        self.assertEqual(rec['project'], 'sandbar')
        self.assertEqual(rec['kind'], 'repair_hatch')
        self.assertLessEqual(abs(rec['at'] - int(time.time() * 1000)), 60000)

    def test_append_only_two_calls_first_line_byte_identical(self):
        self.hatch()
        first = self.read_lines()[0]
        self.hatch(revisions=['ffff999'])
        lines = self.read_lines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], first)  # 追加不改前文
        self.assertNotEqual(json.loads(lines[1])['id'], json.loads(lines[0])['id'])

    def test_failed_validation_touches_nothing(self):
        with self.assertRaises(ValueError):
            self.hatch(by=None)
        with self.assertRaises(ValueError):
            self.hatch(expires='nope')
        self.assertFalse(self.records_file().exists())

    def test_expires_round_trips_exactly(self):
        out = self.hatch()
        rec = json.loads(self.read_lines()[0])
        self.assertEqual(rec['expires'], out['expires'])  # T1.2 落地时刻过期复查靠这个字段
        self.assertEqual(rec['expires'], self.ok['expires'])

    def test_ids_never_reused(self):
        a = self.hatch()['hatch_id']
        b = self.hatch()['hatch_id']
        self.assertNotEqual(a, b)
        lines = self.read_lines()
        self.assertNotEqual(json.loads(lines[0])['id'], json.loads(lines[1])['id'])


class TestRefusalBattery(HatchTestBase):
    """畸形输入逐字段拒收（必带面；全部具名、零落账）。"""

    def _refused(self, **over):
        before = self.read_lines() if self.records_file().exists() else []
        with self.assertRaises(ValueError) as cm:
            self.hatch(**over)
        msg = str(cm.exception)
        self.assertGreater(len(msg.strip()), 10, '拒收必须带人话原因')
        after = self.read_lines() if self.records_file().exists() else []
        self.assertEqual(before, after, '拒收零落账')
        return msg

    def test_missing_project(self):
        self._refused(project=None)

    def test_bad_project_key_shape(self):
        self._refused(project='NOT_A_KEY!')

    def test_who_blank_and_missing(self):
        self._refused(by=None)
        self._refused(by='   ')

    def test_who_agent_role_name_normalized(self):
        self._refused(by='developer')
        self._refused(by='  INTEGRATION ')
        self._refused(by='ops')

    def test_who_agent_display_name_family(self):
        self._refused(by='developer-agent')
        self._refused(by='Some-AGENT')

    def test_who_over_length_cap(self):
        self._refused(by='x' * 65)

    def test_expires_missing_past_and_unparseable(self):
        self._refused(expires=None)
        self._refused(expires=int(time.time()) - 1)
        self._refused(expires=0)
        self._refused(expires='2000-01-01T00:00:00')
        self._refused(expires='not-a-date')
        self._refused(expires=True)

    def test_breakage_missing_and_empty(self):
        self._refused(breakage=None)
        self._refused(breakage='   ')

    def test_breakage_both_forms_ambiguous(self):
        self._refused(breakage={'known_issue': 'KI-001', 'description': 'x'})

    def test_known_issue_unknown_id(self):
        self._refused(breakage={'known_issue': 'KI-999999'})

    def test_known_issue_bad_shape(self):
        self._refused(breakage={'known_issue': 'NOPE-1'})
        self._refused(breakage={'known_issue': 'KI-'})

    def test_revisions_missing_empty_blank_entry(self):
        self._refused(revisions=None)
        self._refused(revisions=[])
        self._refused(revisions=['   '])
        self._refused(revisions=['x' * 65])

    def test_malformed_payload_shapes(self):
        self._refused(revisions='abc,,def')
        self._refused(revisions='abc, ,def')
        self._refused(breakage=12345)


class TestTicketPathGuard(HatchTestBase):
    def test_refused_by_name_under_lane_root(self):
        # 票路径闸比对 ticket.REPO/.lane（与 _resolve_caller 同一 cwd 口径）。
        # 测试 checkout 里该目录可能不存在——realpath 不要求存在，故在
        # REPO/.lane 下造临时目录做真实命中面，用完即清。
        lane_dir = REPO / '.lane' / 'tmp_hatch_guard_case'
        lane_dir.mkdir(parents=True, exist_ok=True)
        old = os.getcwd()
        os.chdir(lane_dir)
        try:
            with self.assertRaises(ValueError) as cm:
                self.hatch()
            self.assertIn('repair_hatch_refused_from_ticket_path', str(cm.exception))
        finally:
            os.chdir(old)
            try:
                lane_dir.rmdir()  # 只清自建的临时目录；.lane 本体他人目录不动
            except OSError:
                pass
        self.assertFalse(self.records_file().exists())

    def test_refused_at_repo_lane_root_itself(self):
        self.assertTrue(tk.caller_from_ticket_path('/repo/.lane', '/repo', []))
        self.assertTrue(tk.caller_from_ticket_path('/repo/.lane/t261009-13/x', '/repo', []))
        # 相似前缀目录不算泳道内：/repo/.lanefoo 不该命中 /repo/.lane
        self.assertFalse(tk.caller_from_ticket_path('/repo/.lanefoo/x', '/repo', []))

    def test_foreign_checkout_lane_worktree_refused_own_checkout_root_allowed(self):
        # 集成闸在泳道 worktree 里跑本文件：cwd=checkout 根（自身即 .lane/t…）必须放行
        self.assertFalse(tk.caller_from_ticket_path(
            '/main/.lane/t261009-13', '/main/.lane/t261009-13', []))
        self.assertFalse(tk.caller_from_ticket_path(
            '/main/.lane/t261009-13/server/tools', '/main/.lane/t261009-13', []))
        # 别的 checkout（含 tmp 仿造）的票泳道 → 拒
        self.assertTrue(tk.caller_from_ticket_path(
            '/tmp/x/fakerepo/.lane/t261009-13-fakelane', '/main/.lane/t261009-13', []))
        self.assertTrue(tk.caller_from_ticket_path(
            '/main/.lane/t261001-01/x', '/main', []))

    def test_outside_lane_roots_allowed(self):
        self.assertFalse(tk.caller_from_ticket_path('/somewhere/else', '/repo', ['/other/lane']))
        self.assertTrue(tk.caller_from_ticket_path('/other/lane/deep', '/repo', ['/other/lane']))


class TestFailClosedStore(HatchTestBase):
    def test_corrupt_line_refused_with_line_number(self):
        self.hatch()
        with self.records_file().open('a', encoding='utf-8') as f:
            f.write('{not json\n')
        with self.assertRaises(ValueError) as cm:
            tk.run({'op': 'hatch_debts', 'project': 'sandbar'})
        self.assertIn('第 2 行', str(cm.exception))
        with self.assertRaises(ValueError):
            self.hatch(revisions=['eee111'])  # 坏账上连合法追加也拒收（fail-closed）
        lines = self.read_lines()
        self.assertEqual(len(lines), 2)  # 原 1 行 + 坏行，没有第三行

    def test_record_missing_v_or_id_refused(self):
        self.hatch()
        with self.records_file().open('a', encoding='utf-8') as f:
            f.write(json.dumps({'v': 'hatch-authorisation-v1'}) + '\n')
        with self.assertRaises(ValueError):
            tk.run({'op': 'hatch_debts', 'project': 'sandbar'})

    def test_duplicate_id_refused(self):
        self.hatch()
        rec = json.loads(self.read_lines()[0])
        with self.records_file().open('a', encoding='utf-8') as f:
            f.write(json.dumps(rec) + '\n')
        with self.assertRaises(ValueError) as cm:
            tk.run({'op': 'hatch_debts', 'project': 'sandbar'})
        self.assertIn('id 重复', str(cm.exception))

    def test_missing_store_reads_empty(self):
        out = tk.run({'op': 'hatch_debts', 'project': 'sandbar'})
        self.assertEqual((out['count'], out['outstanding_count']), (0, 0))
        self.assertEqual(out['debts'], [])


class TestDebtAndCoverage(HatchTestBase):
    def hatch_rec(self, revisions, **over):
        out = self.hatch(revisions=revisions, **over)
        return json.loads(self.read_lines()[-1])

    def append_raw(self, rec):
        with self.records_file().open('a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')

    def test_debt_lists_authority_breakage_time(self):
        self.hatch_rec(['abc1234'])
        out = tk.run({'op': 'hatch_debts', 'project': 'sandbar'})
        self.assertEqual(out['outstanding_count'], 1)
        d = out['debts'][0]
        self.assertEqual(d['by'], self.ok['by'])
        self.assertEqual(d['revisions'], ['abc1234'])
        self.assertTrue(d['outstanding'])
        self.assertIsNone(d['covered_by'])
        self.assertIn('description', d['breakage'])

    def test_certification_covering_full_set_clears_debt(self):
        self.hatch_rec(['abc1234', 'def5678'])
        self.append_raw({'v': 'certification-v1', 'id': 'cert-1', 'project': 'sandbar',
                         'revisions': ['abc1234', 'def5678']})
        out = tk.run({'op': 'hatch_debts', 'project': 'sandbar'})
        self.assertEqual(out['outstanding_count'], 0)
        self.assertEqual(out['debts'][0]['covered_by'], 'cert-1')

    def test_partial_coverage_stays_outstanding(self):
        self.hatch_rec(['abc1234', 'def5678'])
        self.append_raw({'v': 'certification-v1', 'id': 'cert-2', 'project': 'sandbar',
                         'revisions': ['abc1234']})
        out = tk.run({'op': 'hatch_debts', 'project': 'sandbar'})
        self.assertEqual(out['outstanding_count'], 1)
        self.assertIsNone(out['debts'][0]['covered_by'])

    def test_coverage_is_project_scoped(self):
        self.hatch_rec(['abc1234'])
        self.append_raw({'v': 'certification-v1', 'id': 'cert-3', 'project': 'otherproj',
                         'revisions': ['abc1234']})
        out = tk.run({'op': 'hatch_debts', 'project': 'sandbar'})
        self.assertEqual(out['outstanding_count'], 1)

    def test_debts_face_grants_nothing_write_only_op_is_repair_hatch(self):
        out = tk.run({'op': 'hatch_debts', 'project': 'sandbar'})
        self.assertNotIn('authorized', json.dumps(out))


class TestSingleHatchAssertion(HatchTestBase):
    def test_forged_second_landing_family_trips_assertion(self):
        with self.assertRaises(ValueError) as cm:
            tk.assert_single_hatch({'hatch-authorisation-v1', 'hatch-express-v1'})
        self.assertIn('第二扇紧急通道', str(cm.exception))

    def test_known_families_pass(self):
        tk.assert_single_hatch({'hatch-authorisation-v1'})
        tk.assert_single_hatch({'hatch-authorisation-v1', 'certification-v1'})
        tk.assert_single_hatch(set())

    def test_store_rejects_unknown_family_records(self):
        self.hatch()
        with self.records_file().open('a', encoding='utf-8') as f:
            f.write(json.dumps({'v': 'hatch-express-v1', 'id': 'x1', 'revisions': ['r1']}) + '\n')
        with self.assertRaises(ValueError) as cm:
            tk.run({'op': 'hatch_debts', 'project': 'sandbar'})
        self.assertIn('hatch-express-v1', str(cm.exception))
        with self.assertRaises(ValueError):
            self.hatch(revisions=['eee111'])  # 写路径同闸

    def test_dispatch_table_has_exactly_one_store_writer(self):
        import inspect
        src = inspect.getsource(tk)
        writers = [name for name in ('_repair_hatch',) if 'def %s(' % name in src]
        self.assertEqual(writers, ['_repair_hatch'])
        # 唯一会调 _hatch_append 的 op 处理器
        callers = [l.strip() for l in src.splitlines() if '_hatch_append(' in l]
        self.assertEqual([c for c in callers if not c.startswith('#') and 'def ' not in c],
                         ['rec_id = _hatch_append(path, record)'])
        # 断言锚本身把 landing 族钉死为一
        self.assertEqual(tk._HATCH_LANDING_FAMILIES, ('hatch-authorisation-v1',))


class TestKiRegistryCheck(HatchTestBase):
    def test_ki_known_in_table_shapes(self):
        text = '| KI-001 | old | open |\n| KI-01J9Z6QK3M7X2P4T8V0N5R | new | open |\n'
        self.assertTrue(tk._ki_known_in('KI-001', text))
        self.assertTrue(tk._ki_known_in('KI-01J9Z6QK3M7X2P4T8V0N5R', text))
        self.assertFalse(tk._ki_known_in('KI-002', text))
        self.assertFalse(tk._ki_known_in('KI-001x', text))

    def test_real_known_issue_id_accepted_end_to_end(self):
        ki_text = (REPO / 'notes' / 'debts' / 'known-issues.md').read_text(encoding='utf-8',
                                                                           errors='replace')
        if not tk._ki_known_in('KI-001', ki_text):
            self.skipTest('KI-001 not present in this checkout')
        out = self.hatch(breakage={'known_issue': 'KI-001'})
        rec = json.loads(self.read_lines()[0])
        self.assertEqual(rec['breakage'], {'known_issue': 'KI-001'})
        self.assertIn('hatch_id', out)


class TestIdMinting(unittest.TestCase):
    def test_mint_avoids_existing_and_is_timestamped(self):
        existing = {'hatch-123-0001'}
        got = tk._hatch_mint_id(123, existing)
        self.assertTrue(got.startswith('hatch-123-'))
        self.assertNotIn(got, existing)


class TestExpiresParsing(unittest.TestCase):
    def test_epoch_and_iso_forms(self):
        now = int(time.time())
        self.assertEqual(tk._hatch_parse_expires(now + 100), now + 100)
        self.assertEqual(tk._hatch_parse_expires(str(now + 100)), now + 100)
        self.assertGreaterEqual(tk._hatch_parse_expires('2099-01-01T00:00:00'), now)

    def test_bad_forms(self):
        for bad in (None, '', 'x', True, -5):
            with self.assertRaises(ValueError):
                tk._hatch_parse_expires(bad)


if __name__ == '__main__':
    unittest.main()
