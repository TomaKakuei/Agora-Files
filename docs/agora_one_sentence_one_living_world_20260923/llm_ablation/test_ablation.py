"""Checks of treatment isolation and denominators; no model calls."""
import unittest
from copy import deepcopy
from pathlib import Path
import run_ablation as r

class AblationChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b=r.runtime()
        cls.world=r.read(r.HERE/'prepared_worlds.json')[0]['world']
        cls.config=r.read(r.HERE/'inputs'/f'{cls.world}.json')
        cls.state=cls.b.AgentStateBundleSpec.model_validate(r.read(r.HERE/'inputs'/f'{cls.world}_initial_state.json'))
        cls.events=[dict(event_id='task',round_index=5,event_type='human_request',content='Repair the press',status='active'),
                    dict(event_id='prior',round_index=6,event_type='model_action',content='Prior exchange',status='success')]
    def payload(self,condition):
        return r.prompt_payload(self.b,self.config,self.state,self.state,self.events,9,{'content':'current rejection'},condition)
    def test_history_mask_changes_only_episodic_field(self):
        full=self.payload('full');ablated=self.payload('no_event_history')
        self.assertTrue(full['recent_events']);self.assertEqual(ablated['recent_events'],[])
        full['recent_events']=[];self.assertEqual(full,ablated)
        self.assertEqual(len(ablated['current_tasks']),1)
        self.assertEqual(ablated['intervention'],{'content':'current rejection'})
    def test_catalog_condition_retains_state_tasks_and_history(self):
        full=self.payload('full');closed=self.payload('catalog_only')
        full['available_action_types']=['catalog','move'];full['open_action_examples']=[]
        self.assertEqual(full,closed)
        props=r.schema_for(self.b,'catalog_only')['properties']['actions']['items']['properties']
        self.assertEqual(props['action_type']['enum'],['catalog','move'])
        self.assertNotIn('proposal',props)
        self.assertIn('proposal',r.schema_for(self.b,'full')['properties']['actions']['items']['properties'])
    def test_no_mutation_of_shared_state_or_events(self):
        before=self.b._state_hash(self.state);events=deepcopy(self.events);config=deepcopy(self.config)
        for c in r.CONDITIONS:self.payload(c)
        self.assertEqual(before,self.b._state_hash(self.state));self.assertEqual(events,self.events);self.assertEqual(config,self.config)
    def test_relation_or_status_does_not_count_as_material_change(self):
        state=self.state.model_copy(deep=True);before=r.digest(r.material_state(state))
        state.agents[0].private_notes+=' updated'
        state.agents[0].public_state['test_status']='resolved'
        self.assertEqual(before,r.digest(r.material_state(state)))
        state.agents[0].room_id='moved_room'
        self.assertNotEqual(before,r.digest(r.material_state(state)))
    def test_failed_calls_still_in_planned_denominator(self):
        trace={'checkpoints':[1,5,9,13,17,21],'events':[],
               'blocks':[{'telemetry':[],'shape_valid':False,'status':'error'} for _ in range(6)]}
        m=r.summarize_trace(trace)
        self.assertEqual(m['planned_slots'],72);self.assertEqual(m['api_errors'],6)
        self.assertEqual(m['success_per_planned_slot'],0);self.assertIsNone(m['success_per_attempt'])
    def test_unknown_condition_rejected(self):
        with self.assertRaises(ValueError):self.payload('typo')

if __name__=='__main__':unittest.main()
