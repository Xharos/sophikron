import assert from 'node:assert/strict';
import { test } from 'node:test';
import { resolveCollisions, stepFloatingNode } from '../src/lib/curriculumMotion.ts';
import {
	programmeScene,
	layoutGraph,
	type CurriculumSubject,
	type CompetencyGraph
} from '../src/lib/curricula.ts';

test('dragged nodes stay pinned and return gently towards their anchor after release', () => {
	const node = { x: 180, y: 90, vx: 0, vy: 0, pinned: true };
	const anchor = { id: 1, x: 0, y: 0 };
	stepFloatingNode(node, anchor, 0, 1 / 60, false);
	assert.equal(node.x, 180);
	node.pinned = false;
	stepFloatingNode(node, anchor, 0, 1 / 60, false);
	assert.ok(node.x < 180 && node.x > 170);
	for (let i = 1; i < 300; i++) stepFloatingNode(node, anchor, i / 60, 1 / 60, false);
	assert.ok(Math.hypot(node.x, node.y) < 8);
	stepFloatingNode(node, anchor, 8, 1 / 60, true);
	assert.equal(node.x, 0);
	assert.equal(node.y, 0);
});

test('collisions push neighbours away without moving the dragged node', () => {
	const pinned = { x: 0, y: 0, vx: 0, vy: 0, pinned: true };
	const neighbour = { x: 15, y: 0, vx: 0, vy: 0, pinned: false };
	resolveCollisions([
		{ id: 1, state: pinned, width: 140, height: 60 },
		{ id: 2, state: neighbour, width: 140, height: 60 }
	]);
	assert.equal(pinned.x, 0);
	assert.equal(pinned.y, 0);
	assert.equal(neighbour.x, 15);
	assert.ok(neighbour.vx > 25, 'A nearby block should receive a noticeable magnetic impulse.');
	for (let i = 0; i < 600; i++) {
		resolveCollisions(
			[
				{ id: 1, state: pinned, width: 140, height: 60 },
				{ id: 2, state: neighbour, width: 140, height: 60 }
			],
			Math.exp((-i / 60) * 2.5)
		);
		stepFloatingNode(neighbour, { id: 2, x: -180, y: 0 }, i / 60, 1 / 60, false);
	}
	assert.ok(Math.abs(neighbour.x + 180) < 8);
});

test('an isolated subject spreads its children around a circle', () => {
	const scene = {
		curriculum_id: 1,
		subject_id: 1,
		version: 0,
		nodes: [-1, 1, 2, 3, 4].map((id) => ({
			id,
			name: String(id),
			code: null,
			color: null,
			semester: null,
			knowledge: null,
			comment: null,
			position: id
		})),
		edges: [1, 2, 3, 4].map((id) => ({ parent_id: -1, child_id: id }))
	};
	const points = layoutGraph(scene, new Set([-1]), '#4361EE');
	assert.equal(points.length, 5);
	assert.ok(points.every((p) => Number.isFinite(p.x) && Number.isFinite(p.y)));
	const root = points.find((p) => p.id === -1)!;
	const children = points.filter((p) => p.id > 0);
	const distances = children.map((p) => Math.hypot(p.x - root.x, p.y - root.y));
	assert.ok(Math.max(...distances) - Math.min(...distances) < 0.001);
	assert.ok(children.some((p) => p.x > root.x + 100) && children.some((p) => p.x < root.x - 100));
});

test('subjects are master nodes and their competency roots appear only after expansion', () => {
	const subject: CurriculumSubject = {
		id: 1,
		name: 'SII',
		icon: 'engineering',
		color: '#4361EE',
		is_active: true,
		can_edit: true
	};
	const graph: CompetencyGraph = {
		curriculum_id: 1,
		subject_id: 1,
		version: 0,
		nodes: [
			{
				id: 7,
				name: 'Analyser',
				code: 'A',
				color: null,
				semester: null,
				comment: null,
				knowledge: null,
				position: 0
			}
		],
		edges: []
	};
	const scene = programmeScene([subject], { 1: graph });
	assert.deepEqual(
		layoutGraph(scene, new Set(), '#4361EE').map((p) => p.id),
		[-1]
	);
	assert.deepEqual(
		new Set(layoutGraph(scene, new Set([-1]), '#4361EE').map((p) => p.id)),
		new Set([-1, 7])
	);
});
