import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
	allocatedWishSubjects,
	completeWishEntries,
	compareWishPeople,
	roomSelectionKey,
	promotionPreferenceText,
	wishBalance,
	wishSessions,
	kholloscopeStepStates,
	type KholloscopeWorkflow,
	type KholleWishes
} from '../src/lib/kholleWishes.ts';
import type { GenerationView } from '../src/lib/kholloscopeGeneration.ts';

function savedPreparation(): KholloscopeWorkflow {
	return {
		school_year: 2026,
		revision: 'a',
		errors: [],
		wish_errors: [],
		validated: { volumes: true, wishes: true, service: true },
		available: { volumes: true, wishes: true, service: true },
		review: { volumes: false, wishes: false, service: false },
		conflicts: { volumes: [], wishes: [], service: [] },
		needs: {},
		subjects: [],
		rooms: [],
		selected_rooms: [],
		teacher_preferences: []
	};
}

function completedGeneration(): GenerationView {
	return {
		source_revision: 'a',
		ready: true,
		run: {
			id: 'a',
			revision: 'a',
			status: 'completed',
			stale: false,
			logs: [],
			rules: {
				rounding: 'none',
				teacher_lunch: true,
				teacher_lunch_minutes: 55,
				recovery_weeks: 1,
				max_per_day: 2,
				time_limit: 60,
				preserve_locks: true,
				optimize: false
			},
			result: {
				saved: true,
				sessions: [],
				template: [],
				moved: 0,
				applied: false,
				quotas: [],
				mappings: [{ calendar_id: 1, track: 1, group: 1 }],
				reference: '2026-09-07'
			}
		}
	};
}

test('editing wishes after only volumes were saved does not turn untouched descendants orange', () => {
	const workflow = savedPreparation();
	workflow.validated.wishes = workflow.validated.service = false;
	workflow.available.service = false;
	const generation: GenerationView = { source_revision: 'a', ready: false, run: null };
	const states = kholloscopeStepStates(workflow, generation, 'wishes', 'wishes');
	assert.equal(states[1].review, false); // First completion, not a reconfirmation.
	assert.equal(states[1].pending, true);
	assert.deepEqual(
		states.slice(0, 5).map((s) => s.validated),
		[true, false, false, false, false]
	);
	assert.deepEqual(
		states.slice(0, 5).map((s) => s.review || s.pending),
		[false, true, false, false, false]
	);
	assert.deepEqual(
		states.slice(0, 5).map((s) => s.available),
		[true, true, false, false, false]
	);
	const restored = kholloscopeStepStates(workflow, generation, 'wishes');
	assert.deepEqual(
		restored.slice(0, 5).map((s) => s.review || s.pending),
		[false, true, false, false, false]
	);
});

test('commitment balance uses the subject period rather than assuming two weeks', () => {
	assert.equal(wishBalance([4, 6], 10 / 6, 6).label, 'Volumes équilibrés');
	assert.equal(wishBalance([4, 6], 10 / 6, 2).label, 'Volume excédentaire');
});

test('a completed solution unlocks groups only after explicit persistent confirmation', () => {
	const generation = completedGeneration();
	if (!generation.run?.result) throw new Error('Missing fixture result');
	generation.run.result.mappings = [];
	generation.run.result.saved = false;
	const pending = kholloscopeStepStates(savedPreparation(), generation, 'generation');
	assert.equal(pending[3].validated, false);
	assert.equal(pending[3].pending, true);
	assert.equal(pending[4].available, false);
	assert.equal(pending[4].pending, false);
	generation.run.result.saved = true;
	const reloaded = JSON.parse(JSON.stringify(generation)) as GenerationView;
	const saved = kholloscopeStepStates(savedPreparation(), reloaded, 'groups');
	assert.equal(saved[3].validated, true);
	assert.equal(saved[4].available, true);
	assert.equal(saved[4].pending, true);
	generation.run.result.saved = false;
	assert.equal(
		kholloscopeStepStates(savedPreparation(), generation, 'generation')[4].available,
		false
	);
});

test('editing service never highlights generation or groups when neither was completed', () => {
	const workflow = savedPreparation();
	for (const confirmedService of [false, true]) {
		workflow.validated.service = confirmedService;
		const states = kholloscopeStepStates(workflow, null, 'service', 'service');
		assert.deepEqual(
			states.slice(0, 5).map((s) => s.review || s.pending),
			[false, false, true, false, false]
		);
		assert.deepEqual(
			states.slice(0, 5).map((s) => s.available),
			[true, true, true, false, false]
		);
	}
	const saved = kholloscopeStepStates(workflow, null, 'service');
	assert.deepEqual(
		saved.slice(0, 5).map((s) => s.validated),
		[true, true, true, false, false]
	);
	assert.deepEqual(
		saved.slice(0, 5).map((s) => s.review || s.pending),
		[false, false, false, true, false]
	);
});

test('invalidating a completed calendar does not mark never-assigned groups as a reconfirmation', () => {
	const generation = completedGeneration();
	if (!generation.run?.result) throw new Error('Missing fixture result');
	generation.run.result.mappings = [];
	generation.run.stale = true;
	const states = kholloscopeStepStates(savedPreparation(), generation, 'generation');
	assert.equal(states[3].review, true);
	assert.equal(states[4].review || states[4].pending, false);
	assert.equal(states[4].available, false);
});

test('failed generation stays orange and cannot unlock or highlight groups after Service is saved', () => {
	const generation = completedGeneration();
	if (!generation.run) throw new Error('Missing fixture run');
	generation.run.status = 'infeasible';
	generation.run.stale = true;
	generation.run.result = null;
	const steps = kholloscopeStepStates(savedPreparation(), generation, 'service');
	assert.deepEqual(
		steps.slice(0, 5).map((s) => s.validated),
		[true, true, true, false, false]
	);
	assert.deepEqual(
		steps.slice(0, 5).map((s) => s.available),
		[true, true, true, true, false]
	);
	assert.equal(steps[3].pending, true);
	assert.equal(steps[4].review || steps[4].pending, false);
});

test('unsaved service changes invalidate generation and groups immediately, without navigation', () => {
	const workflow = savedPreparation();
	const generation = completedGeneration();
	const steps = kholloscopeStepStates(workflow, generation, 'service', 'service');
	assert.deepEqual(
		steps.slice(0, 5).map((s) => s.validated),
		[true, true, false, false, false]
	);
	assert.deepEqual(
		steps.slice(0, 5).map((s) => s.review),
		[false, false, true, true, true]
	);
	assert.deepEqual(
		steps.slice(0, 5).map((s) => s.available),
		[true, true, true, false, false]
	);
});

test('a stale completed draft cannot unlock groups even when its old mappings still exist', () => {
	const generation = completedGeneration();
	if (!generation.run) throw new Error('Missing fixture run');
	generation.run.stale = true;
	const steps = kholloscopeStepStates(savedPreparation(), generation, 'generation');
	assert.deepEqual(
		steps.slice(0, 5).map((s) => s.validated),
		[true, true, true, false, false]
	);
	assert.equal(steps[3].review, true);
	assert.equal(steps[4].review, true);
	assert.equal(steps[4].available, false);
});

test('unconfirmed preparation locks every later route even with a completed generation response', () => {
	for (const first of ['volumes', 'wishes', 'service'] as const) {
		const workflow = savedPreparation();
		workflow.validated[first] = false;
		workflow.review[first] = true;
		const states = kholloscopeStepStates(workflow, completedGeneration(), 'groups');
		const index = ['volumes', 'wishes', 'service'].indexOf(first);
		assert.deepEqual(
			states.slice(0, 5).map((s) => s.validated),
			states.slice(0, 5).map((_, i) => i < index)
		);
		assert.deepEqual(
			states.slice(0, 5).map((s) => s.available),
			states.slice(0, 5).map((_, i) => i <= index)
		);
		assert.deepEqual(
			states.slice(0, 5).map((s) => s.review),
			states.slice(0, 5).map((_, i) => i >= index)
		);
	}
});

test('visiting saved preparation preserves its green state and published steps remain readable', () => {
	const workflow = savedPreparation();
	for (const tab of ['volumes', 'wishes', 'service', 'generation', 'groups'] as const) {
		assert.ok(
			kholloscopeStepStates(workflow, completedGeneration(), tab)
				.slice(0, 5)
				.every((s) => s.validated)
		);
	}
	const generation = completedGeneration();
	if (!generation.run?.result) throw new Error('Missing fixture result');
	generation.run.stale = true;
	generation.run.result.applied = true;
	workflow.validated.service = false;
	assert.equal(kholloscopeStepStates(workflow, generation, 'groups')[4].available, true);
});

test('revision is a separate final step, locked until publication even after group assignment', () => {
	const workflow = savedPreparation();
	const generation = completedGeneration();
	const before = kholloscopeStepStates(workflow, generation, 'groups').at(-1);
	assert.equal(before?.id, 'revision');
	assert.equal(before.available, false);
	assert.equal(before.validated || before.pending || before.review, false);
	if (!generation.run?.result) throw new Error('Missing fixture result');
	generation.run.result.applied = true;
	generation.run.stale = true;
	workflow.validated = { volumes: false, wishes: false, service: false };
	workflow.review = { volumes: true, wishes: true, service: true };
	const published = kholloscopeStepStates(workflow, generation, 'revision');
	assert.ok(published.every((step) => step.available));
	assert.ok(published.slice(0, 5).every((step) => step.validated && !step.review));
	assert.equal(published.at(-1)?.current, true);
	assert.equal(published.at(-1)?.validated, true);
	generation.revision_state = { conflicts: true, pending: false };
	assert.equal(kholloscopeStepStates(workflow, generation, 'revision').at(-1)?.pending, true);
	generation.revision_state = { conflicts: false, pending: true };
	assert.equal(kholloscopeStepStates(workflow, generation, 'revision').at(-1)?.pending, true);
	generation.revision_state = { conflicts: false, pending: false };
	assert.equal(kholloscopeStepStates(workflow, generation, 'revision').at(-1)?.validated, true);
	generation.run.result.applied = false;
	generation.run.result.withdrawn = { scope: 'all', removed: 1, at: '2026-09-01' };
	assert.equal(kholloscopeStepStates(workflow, generation, 'revision').at(-1)?.available, false);
});

test('promotion preference labels use singular, plural and indifferent forms', () => {
	assert.equal(promotionPreferenceText(1), 'Sa promotion en priorité');
	assert.equal(promotionPreferenceText(3), 'Ses promotions en priorité');
	assert.equal(promotionPreferenceText(3, true), 'Indifférent');
});

test('saved room sets ignore order and empty selections but detect actual changes', () => {
	assert.equal(
		roomSelectionKey({ 2: [8, 3], 1: [], 4: [9] }),
		roomSelectionKey({ 4: [9], 2: [3, 8] })
	);
	assert.notEqual(roomSelectionKey({ 2: [3, 8] }), roomSelectionKey({ 2: [3] }));
});

test('teachers precede kholleurs with French alphabetical ordering and dual roles stay among teachers', () => {
	const person = (
		id: number,
		last_name: string,
		first_name: string,
		roles: ('teacher' | 'kholleur')[]
	) => ({ id, last_name, first_name, roles });
	const people = [
		person(1, 'Aaron', 'Paul', ['kholleur']),
		person(2, 'Zola', 'Zoé', ['teacher']),
		person(3, 'Émile', 'Alice', ['teacher', 'kholleur']),
		person(4, 'Zola', 'Alice', ['teacher']),
		person(5, 'Bernard', 'Paul', ['kholleur'])
	];
	assert.deepEqual(
		[...people].sort(compareWishPeople).map((person) => person.id),
		[3, 4, 2, 1, 5]
	);
	assert.deepEqual(
		people.map((person) => person.id),
		[1, 2, 3, 4, 5]
	);
});

test('only subjects with allocated kholles appear, including when wishes are still unfilled', () => {
	const subjects: KholleWishes['subjects'] = [1, 2, 3].map((id) => ({
		id,
		name: id === 2 ? 'Allemand' : `Matière ${id}`,
		color: '#123456',
		icon: 'book',
		staff: [
			{
				id: 10,
				name: 'Marie Test',
				first_name: 'Marie',
				last_name: 'Test',
				roles: ['teacher'],
				sessions: id === 2 ? 4 : null
			}
		]
	}));
	assert.deepEqual(
		allocatedWishSubjects(subjects, { 1: 7.5, 3: 0 }).map((subject) => subject.id),
		[1]
	);
	assert.deepEqual(allocatedWishSubjects(subjects, null), []);
	assert.deepEqual(allocatedWishSubjects(subjects, {}), []);
	assert.deepEqual(completeWishEntries(subjects, [{ user_id: 10, subject_id: 1, sessions: 15 }]), [
		{ user_id: 10, subject_id: 1, sessions: 15 },
		{ user_id: 10, subject_id: 2, sessions: 4 },
		{ user_id: 10, subject_id: 3, sessions: null }
	]);
});

test('wishes distinguish blanks, zero and odd cycle commitments', () => {
	assert.equal(wishSessions(''), null);
	assert.equal(wishSessions('  '), null);
	assert.equal(wishSessions('0'), 0);
	assert.equal(wishSessions('15'), 15);
	for (const value of ['-1', '1.5', '1,5', 'abc', '1001', 'Infinity'])
		assert.equal(wishSessions(value), undefined);
});

test('balances identify incomplete, deficient, balanced and excessive service', () => {
	assert.equal(wishBalance([15, 15], 15).label, 'Volumes équilibrés');
	assert.equal(wishBalance([15, 14], 15).difference, -0.5);
	assert.equal(wishBalance([15, 14], 15).label, 'Volume insuffisant');
	assert.equal(wishBalance([15, 16], 15).label, 'Volume excédentaire');
	assert.equal(wishBalance([30, null], 15).label, 'Souhaits incomplets');
	assert.equal(wishBalance([], 15).label, 'Souhaits incomplets');
	assert.equal(wishBalance([0], 0).label, 'Volumes équilibrés');
	assert.equal(wishBalance([15], null).label, 'Besoin non disponible');
});
