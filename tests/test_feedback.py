import json
import unittest

from desk_companion.collaboration import feedback
from desk_companion.integrations.web.web_sources import source_catalog, render_citations, check_citations


class FeedbackTests(unittest.TestCase):
    def test_review_does_not_mix_superseded_source_versions(self):
        from desk_companion.collaboration.feedback_review import material
        old=dict(kind='page',level='body',url='https://example.org/source',text='Old version permits online use.',snapshot_id='a'*32,sha256='1'*64)
        current={**old,'text':'Current version permits offline use only.','snapshot_id':'b'*32,'sha256':'2'*64}
        rows=material('check current limits','draft',[old,current],[])
        body=next(r for r in rows if r['level']=='body')
        self.assertEqual(body['segments'],[current['text']])

    def test_complete_json_citations_are_data_even_without_an_inferred_format_contract(self):
        from desk_companion.collaboration.delivery_feedback import assess
        from desk_companion.infrastructure.json_document import json_answer
        source=dict(level='body',url='https://example.org/rfc',text='RFC 8259 published in 2017.')
        ident=source_catalog([source])[0]['id']
        goal='实际读取头部，只返回JSON number/year/citation。'
        self.assertIsNone(feedback.output_contract(goal))
        original=dict(number=8259,year=2017,citation=f'[{ident}]',code=f'[{ident}]')
        text='```json\n'+json.dumps(original)+'\n```'
        rendered,checks,audit=assess(dict(text=goal,collab_run='test'),text,[source],None,[])
        value=json_answer(rendered)
        self.assertTrue(audit['ok']);self.assertEqual(audit['checked'],1)
        self.assertEqual(value['number'],8259);self.assertEqual(value['year'],2017)
        self.assertEqual(value['code'],original['code']);self.assertIn(source['url'],value['citation'])
        unknown={**original,'citation':'[S000000000000]'}
        _,_,audit=assess(dict(text=goal,collab_run='test'),json.dumps(unknown),[source],None,[])
        self.assertFalse(audit['ok'])
        example='仅供解释的JSON示例：\n'+text
        rendered,_,_=assess(dict(text='解释示例。',collab_run='test'),example,[source],None,[])
        self.assertEqual(rendered,example)

    def test_wire_references_preserve_exact_whitespace_and_cannot_invent_source(self):
        from desk_companion.collaboration.feedback_review import review, excerpt_packet, material
        source=dict(level='body',url='https://example.org/fact',text='    .test\n\t.example\n  observed in 2020.')
        packet,registry=excerpt_packet(material('read','2020',[source],[]))
        body=packet[-1];ident=body['excerpts'][0]['id']
        self.assertNotIn('segments',body)
        self.assertEqual(registry[ident]['quote'],source['text'])
        def call(evidence,dimension='claim_support'):
            return lambda _:dict(message=dict(content=json.dumps(dict(requirements=[dict(requirement='year',dimension=dimension,status='supported',reason='actual source',evidence=evidence)]))))
        result=review('read','2020',[source],[],call([ident]))[0]
        self.assertEqual(result['status'],'pass');self.assertEqual(result['evidence'][0]['quote'],source['text'])
        self.assertEqual(review('read','2020',[source],[],call(['invented']))[0]['status'],'unknown')
        self.assertEqual(review('read','2020',[source],[],call([ident],'reading'))[0]['status'],'unknown')
        self.assertEqual(review('read','2020',[source],[],call([dict(source_id=body['id'],quote=source['text'])]))[0]['status'],'unknown')

    def test_excerpt_packet_never_joins_unread_segments(self):
        from desk_companion.collaboration.feedback_review import excerpt_packet
        packet,registry=excerpt_packet([dict(id='actual',level='body',segments=['A'*700,'B'*200])])
        self.assertEqual([len(e['text'])for e in packet[0]['excerpts']],[600,100,200])
        self.assertEqual(packet[0]['excerpts'][-1]['id'],'E0.1.0')
        self.assertFalse(any('A'in e['quote']and 'B'in e['quote']for e in registry.values()))

    def test_invalid_review_dimension_keeps_unknown_and_reports_safe_repair_path(self):
        from desk_companion.collaboration.feedback_review import review
        item=dict(requirement='PRIVATE_CONTENT_NOT_FOR_DIAGNOSTIC',dimension='format/schema',status='supported',reason='checked',evidence=[])
        captured=[]
        def call(messages):
            captured.append(messages)
            return dict(message=dict(content=json.dumps(dict(requirements=[item]))))
        checks=review('goal','draft',[],[],call)
        self.assertEqual(checks[0]['status'],'unknown')
        issue=checks[0]['protocol_errors'][0]
        self.assertEqual(issue['path'],'/requirements/0/dimension');self.assertEqual(issue['keyword'],'enum')
        self.assertIn('task_acceptance',issue['allowed_values']);self.assertNotIn('format',issue['allowed_values']);self.assertNotIn('format/schema',issue['allowed_values'])
        self.assertNotIn('PRIVATE_CONTENT_NOT_FOR_DIAGNOSTIC',json.dumps(checks))
        review('goal','draft',[],[],call,protocol_issues=checks)
        self.assertEqual(json.loads(captured[-1][1]['content'])['previous_protocol_issues'][0]['protocol_errors'],checks[0]['protocol_errors'])
        noisy=review('goal','draft',[],[],lambda _:dict(message=dict(content=json.dumps(dict(requirements=[item]*30)))))
        self.assertLessEqual(len(noisy[0]['protocol_errors']),8);self.assertTrue(noisy[0]['protocol_errors_truncated'])
        self.assertNotIn('PRIVATE_CONTENT_NOT_FOR_DIAGNOSTIC',json.dumps(noisy))

    def test_review_rendering_stage_is_bound_to_actual_passed_provenance(self):
        from desk_companion.collaboration.feedback_review import review
        captured=[]
        def call(messages):
            captured.append(messages)
            return dict(message=dict(content='{}'))
        rule=dict(id='citation_provenance',dimension='source_url',status='pass',basis='deterministic')
        review('goal','draft',[],[],call,verified_checks=[rule],rendered_delivery='compiled')
        payload=json.loads(captured[-1][1]['content'])
        self.assertEqual(payload['candidate_stage'],'submitted_candidate');self.assertEqual(payload['citation_provenance_rule'],'citation_provenance')
        self.assertEqual(payload['rendered_delivery'],dict(stage='after_citation_resolution',text='compiled'))
        review('goal','draft',[],[],call,verified_checks=[{**rule,'status':'unknown'}])
        self.assertIsNone(json.loads(captured[-1][1]['content'])['citation_provenance_rule'])
        self.assertEqual(json.loads(captured[-1][1]['content'])['candidate_stage'],'submitted_candidate')
        self.assertNotIn('rendered_delivery',json.loads(captured[-1][1]['content']))

    def test_structured_review_submission_is_data_only_and_still_strict(self):
        from desk_companion.collaboration.feedback_review import review
        item=dict(requirement='return the given word',dimension='task_acceptance',status='supported',reason='matches provided input',evidence=['E0.0.0'])
        def call_for(name,items):
            return lambda _:dict(message=dict(tool_calls=[dict(function=dict(name=name,arguments=json.dumps(dict(requirements=items))))]))
        checks=review('red','red',[],[],call_for('submit_feedback_review',[item]))
        self.assertEqual(checks[0]['status'],'pass')
        unknown=review('red','red',[],[],call_for('send_message',[item]))
        self.assertEqual(unknown[0]['status'],'unknown')
        invalid=review('red','red',[],[],call_for('submit_feedback_review',[{**item,'dimension':'format/schema'}]))
        self.assertEqual(invalid[0]['status'],'unknown');self.assertEqual(invalid[0]['protocol_errors'][0]['keyword'],'enum')

    def test_source_integrity_binds_actual_producer_scope_and_latest_environment(self):
        env='a'*32;commit='b'*40
        proof=dict(complete=True,unchanged=True,scope='tracked_files_at_observation',untracked_excluded=True,
            baseline_commit=commit,current_commit=commit,tracked_changes=False,owner=env,environment=env,
            sandbox_id='sdk-uuid',service_id='service',start_operation='start',request_id='request',guest_session='c'*32,
            observed_at=1,observation_finished_at=2,received_at=3,transport='existing_service_pipe',new_exec=False)
        requirement=dict(id='original_source',kind='source_integrity',environment=env,commit=commit)
        actual=dict(tool='project_integrity',call_id='check',arguments=dict(environment=env),result=dict(ok=True,integrity=proof))
        self.assertEqual(feedback.check_receipts([actual],[requirement])[0]['status'],'pass')
        for changes in [dict(owner='different'),dict(new_exec=True),dict(complete=False),dict(untracked_excluded=False),dict(current_commit='d'*40)]:
            row={**actual,'result':dict(ok=True,integrity={**proof,**changes})}
            self.assertEqual(feedback.check_receipts([row],[requirement])[0]['status'],'unknown')
        forged={**actual,'tool':'project_read'}
        self.assertEqual(feedback.check_receipts([forged],[requirement])[0]['status'],'unknown')
        changed={**actual,'result':dict(ok=True,integrity={**proof,'unchanged':False,'tracked_changes':True})}
        self.assertEqual(feedback.check_receipts([changed],[requirement])[0]['status'],'fail')
        failed={**actual,'call_id':'latest','result':dict(ok=False,integrity=dict(complete=False))}
        self.assertEqual(feedback.check_receipts([actual,failed],[requirement])[0]['status'],'unknown')
        write=dict(tool='project_write',call_id='later',arguments=dict(environment=env),result=dict(ok=True))
        self.assertEqual(feedback.check_receipts([actual,write],[requirement])[0]['status'],'unknown')
        stop={**write,'tool':'project_stop'}
        self.assertEqual(feedback.check_receipts([actual,stop],[requirement])[0]['status'],'pass')

    def test_json_citations_preserve_document_and_code_examples(self):
        sources=[dict(url='https://example.org/actual',level='body',text='The launch was in 2020.')]
        ident=source_catalog(sources)[0]['id']
        original=dict(year=2020,citation=f'[{ident}]',code='curl https://api.example.org/not-read')
        rendered,unknown=render_citations('```json\n'+json.dumps(original)+'\n```',sources,structured=True)
        value=feedback.json_answer(rendered)
        self.assertEqual(set(value),set(original));self.assertEqual(value['code'],original['code'])
        self.assertIn('https://example.org/actual',value['citation']);self.assertEqual(unknown,[])
        self.assertTrue(check_citations(rendered,sources,structured=True)['ok'])
        # An ordinary fenced JSON example remains code unless explicitly a JSON answer.
        self.assertFalse(check_citations('```json\n{"url":"https://example.org/actual"}\n```',sources)['ok'])

    def test_json_contract_does_not_accept_extra_prose_or_change_types(self):
        goal='请计算。最终只返回相同JSON。'
        schema=dict(type='object',properties=dict(total=dict(type='integer'),checked=dict(type='boolean')),required=['total','checked'],additionalProperties=False)
        contract=dict(format='json',schema=schema)
        good=feedback.check_output('{"total":18,"checked":true}',goal,contract)
        self.assertTrue(all(x['status']=='pass'for x in good))
        self.assertEqual(feedback.check_output('# 报告\n{"total":18,"checked":true}',goal)[0]['status'],'fail')
        self.assertEqual(feedback.check_output('{"total":true,"checked":true}',goal,contract)[-1]['status'],'fail')
        self.assertIsNone(feedback.output_contract('解释“只返回JSON”是什么意思，请用普通段落。'))
        self.assertIsNone(feedback.output_contract('解释“A，最终只返回JSON，B”这句示例。'))
        self.assertEqual(feedback.check_output('{"total":NaN}',goal)[0]['status'],'fail')
        self.assertEqual(feedback.check_output('{"checked":false,"checked":true}',goal)[0]['status'],'fail')
        self.assertIsNone(feedback.output_contract('只输出JSON。\n最终只返回Markdown。'))
        self.assertEqual(feedback.check_output('# report\n{}','Return only JSON object.')[0]['status'],'fail')
        self.assertEqual(feedback.check_output('not JSON','【输出格式】只返回一个合法 JSON 对象，包含数据。')[0]['status'],'fail')

    def test_remote_schema_reference_is_rejected_without_network(self):
        with self.assertRaises(ValueError):
            feedback.output_contract('x',dict(format='json',schema={'$ref':'https://example.org/schema'}))

    def test_receipt_success_does_not_prove_artifact_or_test_coverage(self):
        checks=feedback.check_receipts([dict(tool='workspace_run',call_id='call1',result=dict(state='succeeded',exit_code=0))],
            [dict(id='build',kind='command',call_id='call1'),dict(id='bundle',kind='artifact',receipt_id='file1'),dict(id='coverage',kind='test_coverage',receipt_id='tests1')])
        by_id={x['id']:x for x in checks}
        self.assertEqual(by_id['build']['status'],'pass')
        self.assertEqual(by_id['bundle']['status'],'unknown')
        self.assertEqual(by_id['coverage']['status'],'unknown')
        self.assertEqual(feedback.report(checks)['completion'],'unverified')

    def test_known_missing_artifact_fails_even_after_exit_zero(self):
        checks=feedback.check_receipts([dict(tool='artifact_check',call_id='file1',result=dict(exists=False))],
            [dict(id='bundle',kind='artifact',receipt_id='file1')])
        self.assertEqual(checks[0]['status'],'fail')
        self.assertEqual(feedback.report(checks)['completion'],'incomplete')

    def test_model_assessment_is_not_deterministic_verification(self):
        checks=[feedback.check('claim','claim_support','pass','审阅认为支持',basis='model_assessment')]
        self.assertEqual(feedback.report(checks)['completion'],'assessed')
        self.assertIn('不代表',feedback.report(checks)['scope'])

    def test_artifact_binds_actual_file_read_and_not_command_claim(self):
        receipts=[dict(tool='workspace_run',call_id='command',arguments=dict(command='echo created'),result=dict(exit_code=0)),
            dict(tool='project_read',call_id='file',arguments=dict(path='dist/index.html'),result=dict(ok=True,kind='file',sha256='a'*64))]
        checks=feedback.check_receipts(receipts,[dict(id='bundle',kind='artifact',path='dist/index.html'),dict(id='wrong',kind='artifact',path='dist/missing.html')])
        self.assertEqual(checks[0]['status'],'pass');self.assertEqual(checks[0]['receipt_id'],'file')
        self.assertEqual(checks[1]['status'],'unknown')

    def test_unknown_operation_identity_survives_feedback(self):
        receipts=[dict(call_id='call',result=dict(operation=dict(id='original',state='unknown'),log_id='log'))]
        record=feedback.report([],receipts=receipts)['unknown_operations'][0]
        self.assertEqual(record['operation_id'],'original');self.assertEqual(record['state'],'unknown')
        self.assertEqual(record['action'],'reconcile_original_receipt_do_not_replay')

    def test_same_path_in_another_environment_cannot_prove_requested_artifact(self):
        rows=[dict(tool='project_read',call_id='file_'+name,arguments=dict(path='dist/index.html',environment=name),result=dict(ok=True,sha256='a'*64))for name in ['A','B']]
        checks=feedback.check_receipts(rows,[dict(id='ambiguous',kind='artifact',path='dist/index.html'),dict(id='bound',kind='artifact',path='dist/index.html',environment='A')])
        self.assertEqual(checks[0]['status'],'unknown');self.assertEqual(checks[1]['receipt_id'],'file_A')

    def test_only_receipt_for_the_same_operation_resolves_unknown(self):
        first=dict(tool='project_prepare',read_only=False,call_id='first',result=dict(operation=dict(id='original',state='unknown')))
        other=dict(tool='project_status',read_only=True,call_id='other',result=dict(operation=dict(id='unrelated',state='succeeded')))
        self.assertEqual(feedback.report([],receipts=[first,other])['completion'],'unverified')
        self.assertEqual(len(feedback.report([],receipts=[first,other])['unknown_operations']),1)
        resolved=dict(tool='project_status',read_only=True,call_id='resolved',result=dict(operation=dict(id='original',state='succeeded')))
        self.assertEqual(feedback.report([],receipts=[first,resolved])['unknown_operations'],[])

    def test_calendar_unconfirmed_and_board_request_ids_use_original_receipts(self):
        calendar=dict(call_id='write',read_only=False,result=dict(operation=dict(id='calendar-op',state='unconfirmed'),change_state='unconfirmed'))
        board=dict(call_id='board',read_only=False,result=dict(request_id='board-op',change_state='unconfirmed'))
        unknown=feedback.pending_operations([calendar,board])
        self.assertEqual({x['operation_id']for x in unknown},{'calendar-op','board-op'})
        observed=dict(call_id='query',read_only=True,result=dict(operation=dict(id='calendar-op',state='synced')))
        loaded=dict(call_id='load',read_only=True,result=dict(ok=True,receipt=dict(request_id='board-op')))
        self.assertEqual(feedback.pending_operations([calendar,board,observed,loaded]),[])

    def test_opaque_write_failure_remains_unknown_but_known_preflight_does_not(self):
        opaque=dict(call_id='attempt',read_only=False,status='failed',result='Error: connection closed')
        self.assertTrue(feedback.pending_operations([opaque])[0]['write_attempted'])
        known=dict(opaque,result=dict(ok=False,change_state='not_changed'))
        self.assertEqual(feedback.pending_operations([known]),[])

    def test_failed_or_in_progress_query_is_not_resolution_of_original_write(self):
        first=dict(call_id='write',read_only=False,result=dict(operation=dict(id='original',state='unknown')))
        for result in [dict(ok=False,request_id='original',error='query failed'),dict(ok=True,operation=dict(id='original',state='running')),
                       dict(ok=False,request_id='original',change_state='not_changed',error='query did not run')]:
            query=dict(call_id='query',read_only=True,result=result)
            pending=feedback.pending_operations([first,query])
            self.assertEqual(len(pending),1);self.assertEqual(pending[0]['operation_id'],'original')

    def test_repair_is_once_and_blocks_mutations_even_when_model_requests_them(self):
        repair=feedback.RepairBudget()
        self.assertTrue(repair.begin());self.assertFalse(repair.begin())
        self.assertFalse(repair.allows('project_create',dict(read_only=False)))
        self.assertFalse(repair.allows('calendar_change',dict(read_only=False)))
        self.assertTrue(repair.allows('project_status',dict(read_only=True)))
        self.assertTrue(repair.allows('build_chart',dict(read_only=False)))

    def test_review_separates_real_source_and_supported_assertion(self):
        from desk_companion.collaboration.feedback_review import material, interpret
        sources=[dict(url='https://example.org/actual',level='body',text='The launch was in 2020.')]
        rows=material('When was launch?','It launched in 2019.',sources,[])
        ident=rows[-1]['id']
        item=dict(requirement='launch year',dimension='claim_support',status='contradicted',reason='2019 conflicts with the read source',evidence=[dict(source_id=ident,quote='The launch was in 2020.')])
        checks=interpret(dict(requirements=[item]),rows)
        self.assertEqual(checks[0]['status'],'fail');self.assertEqual(checks[0]['basis'],'model_assessment')
        item.update(status='supported',evidence=[dict(source_id=ident,quote='The launch was in 2019.')])
        self.assertEqual(interpret(dict(requirements=[item]),rows)[0]['status'],'unknown')

    def test_review_cannot_promote_snippet_or_quote_across_unread_gap(self):
        from desk_companion.collaboration.feedback_review import material, interpret
        sources=[dict(url='https://example.org/actual',level='body',text='first part',snapshot_id='snap',characters=100,read_ranges=[[0,10]],truncated=True),
                 dict(url='https://example.org/actual',level='body',text='last part',snapshot_id='snap',characters=100,read_ranges=[[90,100]],truncated=True)]
        rows=material('read whole','claim',sources,[]);ident=rows[-1]['id']
        item=dict(requirement='claim',dimension='claim_support',status='supported',reason='claimed support',evidence=[dict(source_id=ident,quote='first part\nlast part')])
        self.assertEqual(interpret(dict(requirements=[item]),rows)[0]['status'],'unknown')
        sources[0].update(level='snippet',text='summary')
        rows=material('read whole','claim',sources[:1],[])
        item['evidence']=[dict(source_id=ident,quote='summary')]
        self.assertEqual(interpret(dict(requirements=[item]),rows)[0]['status'],'unknown')



    def test_actual_receipts_can_ground_observations_but_handoffs_are_not_body(self):
        from desk_companion.collaboration.feedback_review import material, interpret
        rows=material('run preview','ready',[],[dict(call_id='start',result=dict(service_ready=True))],
            [dict(id='child',answer='ready')])
        receipt=next(r for r in rows if r['level']=='actual_receipt')
        item=dict(requirement='preview observed',dimension='claim_support',status='supported',reason='actual service receipt',evidence=[dict(source_id=receipt['id'],quote=receipt['segments'][0])])
        self.assertEqual(interpret(dict(requirements=[item]),rows)[0]['status'],'pass')
        handoff=rows[-1];item['evidence']=[dict(source_id=handoff['id'],quote=handoff['segments'][0])]
        self.assertEqual(interpret(dict(requirements=[item]),rows)[0]['status'],'unknown')


    def test_verified_project_observation_is_not_research_body(self):
        from desk_companion.collaboration.feedback_review import material, interpret
        from desk_companion.collaboration.delivery_feedback import assess
        source=dict(kind='project_preview',level='service_preview',url='http://127.0.0.1:12345/',title='verified preview',scope='startup HTTP observation, not research body')
        rows=material('verify startup','verified',[source],[]);row=rows[-1]
        item=dict(requirement='startup observed',dimension='claim_support',status='supported',reason='recorded observation',evidence=[dict(source_id=row['id'],quote=row['segments'][0])])
        check=interpret(dict(requirements=[item]),rows)[0]
        self.assertEqual(check['status'],'pass');self.assertEqual(check['evidence'][0]['level'],'service_preview')
        _,checks,_=assess(dict(text='read research',collab_run='test',required_sources=['web']),'[preview](http://127.0.0.1:12345/)',[source],None,[])
        self.assertTrue(any(c['id']=='required_source_web'and c['status']=='fail'for c in checks))

    def test_child_goal_does_not_inherit_root_output_format(self):
        from desk_companion.collaboration.delivery_feedback import assess
        req=dict(text='只输出JSON对象。',objective='最终用Markdown段落。',parent_run='actual-parent',stage='deliver',collab_run='child')
        _,checks,_=assess(req,'plain text',[],dict(complete=True,missing=[]),[])
        self.assertTrue(any(c['id']=='output_format'and c['status']=='fail'for c in checks))
        self.assertEqual(feedback.current_goal({**req,'parent_run':None}),req['objective'])


    def test_explicit_required_json_prefix_is_not_a_quoted_example(self):
        goal='用户目标：计算7与11。完成条件：你必须只返回一个 JSON 对象，包含total与checked。'
        self.assertEqual(feedback.output_contract(goal),dict(format='json',schema=dict(type='object')))
        self.assertEqual(feedback.check_output('说明 {"total":18}',goal)[0]['status'],'fail')
        self.assertEqual(feedback.check_output('{"total":18}',goal)[0]['status'],'pass')
        for text in ['解释“你必须只返回一个 JSON 对象”的含义。','示例：`你必须只返回JSON`。解释即可。','如果只返回JSON会怎样？']:
            self.assertIsNone(feedback.output_contract(text))



if __name__=='__main__':unittest.main()
