import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
	ancestors,
	descendants,
	compareCodes,
	competencyAppearance,
	competencyFileName,
	competencyOutline,
	competencyLinkPath,
	competencyColors,
	layoutGraph,
	type GraphPoint,
	type CompetencyGraph,
	type Competency
} from '../src/lib/curricula.ts';

function node(id: number): Competency {
	return {
		id,
		name: String(id),
		code: null,
		semester: null,
		knowledge: null,
		comment: null,
		color: null,
		position: id
	};
}
const graph: CompetencyGraph = {
	curriculum_id: 1,
	subject_id: 1,
	version: 0,
	nodes: [node(1), node(2), node(3), node(4)],
	edges: [
		{ parent_id: 1, child_id: 3 },
		{ parent_id: 2, child_id: 3 },
		{ parent_id: 3, child_id: 4 }
	]
};

test('JSON downloads use the subject name with safe portable filename characters', () => {
	assert.equal(competencyFileName('Mathématiques'), 'Mathématiques.json');
	assert.equal(competencyFileName('SII / PTSI:PT'), 'SII _ PTSI_PT.json');
	assert.equal(competencyFileName('CON'), '_CON.json');
	assert.equal(competencyFileName('  ... '), 'competences.json');
	assert.equal(competencyFileName('SII\\PT\u0000'), 'SII_PT_.json');
});

test('collapse hides descendants and shared competencies are rendered only once', () => {
	assert.deepEqual(
		new Set(layoutGraph(graph, new Set(), '#4361EE').map((p) => p.id)),
		new Set([1, 2])
	);
	const points = layoutGraph(graph, new Set([1, 2, 3]), '#4361EE');
	assert.equal(points.length, 4);
	assert.equal(points.filter((p) => p.id === 3).length, 1);
	assert.ok(points.every((p) => Number.isFinite(p.x) && Number.isFinite(p.y)));
});
test('search reveals every ancestor path of a shared node', () => {
	assert.deepEqual(ancestors(4, graph.edges), new Set([1, 2, 3, 4]));
	assert.deepEqual(descendants(1, graph.edges), new Set([1, 3, 4]));
});

test('automatic codes sort by hierarchy instead of lexical string order', () => {
	assert.deepEqual(['AA', 'A.10', 'A.2', 'Z', 'B', 'A.1.a'].sort(compareCodes), [
		'A.1.a',
		'A.2',
		'A.10',
		'B',
		'Z',
		'AA'
	]);
});
test('explicit colors override inherited branch and subject colors', () => {
	const colored = {
		...graph,
		nodes: graph.nodes.map((n) => ({ ...n, color: n.id === 1 ? '#FF0000' : null }))
	};
	const points = layoutGraph(colored, new Set([1]), '#0000FF');
	assert.equal(points.find((p) => p.id === 3)?.color, '#FF0000');
	assert.equal(points.find((p) => p.id === 2)?.color, '#0000FF');
	const colors = competencyColors(colored, '#0000FF');
	assert.equal(colors.get(3), '#FF0000');
	assert.equal(colors.get(4), '#FF0000');
	assert.equal(colors.get(2), '#0000FF');
});

function dimensions(point: GraphPoint): { width: number; height: number } {
	const scale = competencyAppearance(point.depth).scale;
	return point.id < 0 ? { width: 205, height: 80 } : { width: 142 * scale, height: 60 * scale };
}

const fourSubjects: CompetencyGraph = {
	...graph,
	nodes: [-1, -2, -3, -4, ...Array.from({ length: 10 }, (_, i) => i + 1)].map(node),
	edges: [
		...Array.from({ length: 7 }, (_, i) => ({ parent_id: -1, child_id: i + 1 })),
		{ parent_id: 1, child_id: 8 },
		{ parent_id: 1, child_id: 9 },
		{ parent_id: 8, child_id: 10 }
	]
};

test('four subjects pack compactly around one expanded graph without overlapping blocks', () => {
	const points = layoutGraph(fourSubjects, new Set([-1, 1, 8]), '#4361EE');
	assert.equal(points.length, 14);
	const width =
		Math.max(...points.map((p) => p.x + dimensions(p).width / 2)) -
		Math.min(...points.map((p) => p.x - dimensions(p).width / 2));
	const height =
		Math.max(...points.map((p) => p.y + dimensions(p).height / 2)) -
		Math.min(...points.map((p) => p.y - dimensions(p).height / 2));
	assert.ok(width < 1400 && height < 1000, `Compact layout expected, got ${width} by ${height}.`);
	for (let i = 0; i < points.length; i++)
		for (let j = 0; j < i; j++) {
			const a = points[i],
				b = points[j];
			assert.ok(
				Math.abs(a.x - b.x) >= (dimensions(a).width + dimensions(b).width) / 2 + 4 ||
					Math.abs(a.y - b.y) >= (dimensions(a).height + dimensions(b).height) / 2 + 4,
				`Blocks ${a.id} and ${b.id} overlap.`
			);
		}
});

test('subject packing follows the viewport and restoring a hidden subject is deterministic', () => {
	const collapsed = {
		...fourSubjects,
		nodes: fourSubjects.nodes.filter((n) => n.id < 0),
		edges: []
	};
	const landscape = layoutGraph(collapsed, new Set(), '#4361EE', 2.5);
	const portrait = layoutGraph(collapsed, new Set(), '#4361EE', 0.5);
	const range = (points: GraphPoint[], axis: 'x' | 'y'): number =>
		Math.max(...points.map((p) => p[axis])) - Math.min(...points.map((p) => p[axis]));
	assert.ok(range(landscape, 'x') > range(portrait, 'x'));
	assert.ok(range(landscape, 'y') < range(portrait, 'y'));
	const full = layoutGraph(fourSubjects, new Set([-1, 1]), '#4361EE');
	layoutGraph(
		{ ...fourSubjects, nodes: fourSubjects.nodes.filter((n) => n.id !== -2) },
		new Set([-1, 1]),
		'#4361EE'
	);
	assert.deepEqual(layoutGraph(fourSubjects, new Set([-1, 1]), '#4361EE'), full);
});

test('deep levels stay smaller, quieter and slightly further apart with bounded styling', () => {
	const root = competencyAppearance(1),
		child = competencyAppearance(2),
		leaf = competencyAppearance(3),
		deep = competencyAppearance(100);
	assert.ok(root.scale > child.scale && child.scale > leaf.scale);
	assert.ok(root.saturation > child.saturation && child.saturation > leaf.saturation);
	assert.ok(child.spacing > root.spacing && leaf.spacing > child.spacing);
	assert.ok(deep.scale >= 0.8 && deep.saturation >= 0.6 && deep.spacing <= 30);
});

const balancedTree: CompetencyGraph = {
	...graph,
	nodes: [
		node(-1),
		...Array.from({ length: 7 }, (_, i) => ({ ...node(i + 1), code: String.fromCharCode(65 + i) })),
		...Array.from({ length: 35 }, (_, i) => ({
			...node(100 + i),
			code: String.fromCharCode(65 + Math.floor(i / 5)) + '.' + ((i % 5) + 1)
		}))
	],
	edges: [
		...Array.from({ length: 7 }, (_, i) => ({ parent_id: -1, child_id: i + 1 })),
		...Array.from({ length: 35 }, (_, i) => ({
			parent_id: Math.floor(i / 5) + 1,
			child_id: 100 + i
		}))
	]
};
test('seven expanded families keep ordered siblings, disjoint blocks and uncrossed tree links', () => {
	const points = layoutGraph(balancedTree, new Set([-1, 1, 2, 3, 4, 5, 6, 7]), '#4361EE');
	const byId = new Map(points.map((p) => [p.id, p]));

	for (let id = 1; id <= 7; id++) {
		const kids = Array.from({ length: 5 }, (_, i) => byId.get(100 + (id - 1) * 5 + i)!);
		for (let i = 1; i < kids.length; i++)
			assert.ok(
				kids[i].angle! > kids[i - 1].angle!,
				'Siblings keep their code order around their ring.'
			);
		assert.ok(kids.every((p) => Math.abs(p.radius! - kids[0].radius!) < 0.001));
	}

	for (let i = 0; i < points.length; i++)
		for (let j = 0; j < i; j++) {
			const a = points[i],
				b = points[j];
			assert.ok(
				Math.abs(a.x - b.x) >= (dimensions(a).width + dimensions(b).width) / 2 + 4 ||
					Math.abs(a.y - b.y) >= (dimensions(a).height + dimensions(b).height) / 2 + 4,
				'Reserved regions must keep blocks apart.'
			);
		}

	const intersects = (
		a: { x: number; y: number },
		b: { x: number; y: number },
		node: GraphPoint
	): boolean => {
		const box = dimensions(node);
		let lo = 0,
			hi = 1;
		for (const axis of ['x', 'y'] as const) {
			const half = (axis === 'x' ? box.width : box.height) / 2 - 1,
				d = b[axis] - a[axis],
				start = a[axis] - node[axis];
			if (Math.abs(d) < 1e-9) {
				if (Math.abs(start) >= half) return false;
				continue;
			}
			const v = (-half - start) / d,
				w = (half - start) / d;
			lo = Math.max(lo, Math.min(v, w));
			hi = Math.min(hi, Math.max(v, w));
			if (lo >= hi) return false;
		}
		return true;
	};
	for (const edge of balancedTree.edges) {
		const path = competencyLinkPath(byId.get(edge.parent_id)!, byId.get(edge.child_id)!);
		for (let i = 1; i < path.length; i++)
			for (const block of points) {
				if (block.id === edge.parent_id || block.id === edge.child_id) continue;
				assert.ok(
					!intersects(path[i - 1], path[i], block),
					'Links must avoid other families and siblings.'
				);
			}
	}

	const width = Math.max(...points.map((p) => p.x)) - Math.min(...points.map((p) => p.x)) + 205;
	const paths = balancedTree.edges.map((edge) => ({
		edge,
		path: competencyLinkPath(byId.get(edge.parent_id)!, byId.get(edge.child_id)!)
	}));
	const side = (
		a: { x: number; y: number },
		b: { x: number; y: number },
		c: { x: number; y: number }
	): number => (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
	for (let i = 0; i < paths.length; i++)
		for (let j = 0; j < i; j++) {
			const a = paths[i],
				b = paths[j];
			if (
				[a.edge.parent_id, a.edge.child_id].some(
					(id) => id === b.edge.parent_id || id === b.edge.child_id
				)
			)
				continue;
			for (let x = 1; x < a.path.length; x++)
				for (let y = 1; y < b.path.length; y++) {
					const p = a.path[x - 1],
						q = a.path[x],
						r = b.path[y - 1],
						s = b.path[y];
					assert.ok(
						!(side(p, q, r) * side(p, q, s) < -0.001 && side(r, s, p) * side(r, s, q) < -0.001),
						'Links belonging to separate families must not cross.'
					);
				}
		}
	const height = Math.max(...points.map((p) => p.y)) - Math.min(...points.map((p) => p.y)) + 80;
	assert.ok(width * height < 2200000, 'The seven-by-five tree must remain compact.');
});
test('expanding more branches rebalances existing anchors regardless of expansion history', () => {
	const partial = layoutGraph(balancedTree, new Set([-1, 1]), '#4361EE');
	const full = layoutGraph(balancedTree, new Set([-1, 1, 2, 3, 4, 5, 6, 7]), '#4361EE');
	assert.ok(
		partial.some((p) => {
			const q = full.find((q) => q.id === p.id)!;
			return Math.hypot(q.x - p.x, q.y - p.y) > 2;
		})
	);
	assert.deepEqual(layoutGraph(balancedTree, new Set([7, 6, 5, 4, 3, 2, 1, -1]), '#4361EE'), full);
});

test('deep chains and wide families have bounded spacing and ignore hidden descendants', () => {
	const deep = {
		...graph,
		nodes: Array.from({ length: 50 }, (_, i) => node(i + 1)),
		edges: Array.from({ length: 49 }, (_, i) => ({ parent_id: i + 1, child_id: i + 2 }))
	};
	const initial = layoutGraph(deep, new Set([1]), '#4361EE');
	assert.equal(initial.length, 2);
	assert.ok(Math.hypot(initial[1].x - initial[0].x, initial[1].y - initial[0].y) < 300);
	const expanded = layoutGraph(deep, new Set(deep.nodes.map((n) => n.id)), '#4361EE');
	assert.ok(expanded.every((p) => Number.isFinite(p.x) && Number.isFinite(p.y)));
	for (const p of expanded)
		if (p.parentId) {
			const parent = expanded.find((q) => q.id === p.parentId)!;
			assert.ok(Math.hypot(p.x - parent.x, p.y - parent.y) < 300);
		}
});

test('seven roots form a circle and opening a second family reflows the first one', () => {
	const initial = layoutGraph(balancedTree, new Set([-1]), '#4361EE');
	const root = initial.find((p) => p.id === -1)!;
	const roots = initial.filter((p) => p.id > 0);
	assert.equal(roots.length, 7);
	const distances = roots.map((p) => Math.hypot(p.x - root.x, p.y - root.y));
	assert.ok(Math.max(...distances) - Math.min(...distances) < 0.001);
	assert.ok(
		roots.some((p) => p.x > root.x + 100) &&
			roots.some((p) => p.x < root.x - 100) &&
			roots.some((p) => p.y > root.y + 100) &&
			roots.some((p) => p.y < root.y - 100)
	);
	const first = layoutGraph(balancedTree, new Set([-1, 1]), '#4361EE'),
		second = layoutGraph(balancedTree, new Set([-1, 1, 2]), '#4361EE');
	assert.ok(
		first
			.filter((p) => p.parentId === 1)
			.some((p) => {
				const other = second.find((q) => q.id === p.id)!;
				return Math.abs(p.angle! - other.angle!) > 0.01;
			}),
		'The first open family must share space with the newly opened family.'
	);
	for (const layout of [first, second])
		for (let i = 0; i < layout.length; i++)
			for (let j = 0; j < i; j++) {
				const a = layout[i],
					b = layout[j];
				assert.ok(
					Math.abs(a.x - b.x) >= (dimensions(a).width + dimensions(b).width) / 2 + 4 ||
						Math.abs(a.y - b.y) >= (dimensions(a).height + dimensions(b).height) / 2 + 4
				);
			}
	for (const point of second.filter((p) => p.depth > 1)) {
		const parent = second.find((p) => p.id === point.parentId)!;
		assert.ok(point.radius! > parent.radius!);
		assert.ok(point.radius! - parent.radius! <= 231);
	}
});

test('opening a grandchild redistributes space with another already-open family and collapse restores it', () => {
	const deep = {
		...balancedTree,
		nodes: [...balancedTree.nodes, ...Array.from({ length: 5 }, (_, i) => node(200 + i))],
		edges: [
			...balancedTree.edges,
			...Array.from({ length: 5 }, (_, i) => ({ parent_id: 100, child_id: 200 + i }))
		]
	};
	const before = layoutGraph(deep, new Set([-1, 1, 2]), '#4361EE'),
		after = layoutGraph(deep, new Set([-1, 1, 2, 100]), '#4361EE');
	assert.ok(
		before
			.filter((p) => p.parentId === 2)
			.some((p) => Math.abs(p.angle! - after.find((q) => q.id === p.id)!.angle!) > 0.001)
	);
	assert.ok(
		after
			.filter((p) => p.id >= 200)
			.every((p) => p.radius! > after.find((q) => q.id === 100)!.radius!)
	);
	for (let i = 0; i < after.length; i++)
		for (let j = 0; j < i; j++) {
			const a = after[i],
				b = after[j];
			assert.ok(
				Math.abs(a.x - b.x) >= (dimensions(a).width + dimensions(b).width) / 2 + 4 ||
					Math.abs(a.y - b.y) >= (dimensions(a).height + dimensions(b).height) / 2 + 4
			);
		}
	assert.deepEqual(layoutGraph(deep, new Set([-1, 1, 2]), '#4361EE'), before);
});

test('links connect block borders directly even when the blocks occupy different ring angles', () => {
	const parent: GraphPoint = {
		id: 1,
		x: 250,
		y: 0,
		radius: 250,
		orbitX: 0,
		orbitY: 0,
		depth: 1,
		color: '#4361EE'
	};
	const child: GraphPoint = {
		id: 2,
		parentId: 1,
		x: 440 * Math.cos(0.6),
		y: 440 * Math.sin(0.6),
		radius: 440,
		orbitX: 0,
		orbitY: 0,
		depth: 2,
		color: '#4361EE'
	};
	const path = competencyLinkPath(parent, child);
	assert.equal(path.length, 2);
	for (const point of path)
		assert.ok(
			Math.abs(
				(point.x - parent.x) * (child.y - parent.y) - (point.y - parent.y) * (child.x - parent.x)
			) < 1e-6
		);
	for (const [index, node] of [parent, child].entries()) {
		const box = dimensions(node),
			point = path[index];
		assert.ok(
			Math.abs(
				Math.max(
					Math.abs(point.x - node.x) / (box.width / 2),
					Math.abs(point.y - node.y) / (box.height / 2)
				) - 1
			) < 1e-6
		);
	}
	assert.ok(
		Math.hypot(path[1].x - path[0].x, path[1].y - path[0].y) <
			Math.hypot(child.x - parent.x, child.y - parent.y)
	);
});

test('the text outline groups descendants immediately under their parent and inherits branch colors', () => {
	const input = {
		...graph,
		nodes: [
			{ ...node(4), code: 'B' },
			{ ...node(3), code: 'A.1.a' },
			{ ...node(2), code: 'A.1' },
			{ ...node(1), code: 'A', color: '#aa2244' }
		],
		edges: [
			{ parent_id: 1, child_id: 2 },
			{ parent_id: 2, child_id: 3 }
		]
	};
	const rows = competencyOutline(input, '#4361EE');
	assert.deepEqual(
		rows.map((row) => row.node.id),
		[1, 2, 3, 4]
	);
	assert.deepEqual(
		rows.map((row) => row.depth),
		[0, 1, 2, 0]
	);
	assert.equal(rows[2].color, '#aa2244');
	assert.equal(rows[2].parentColor, '#aa2244');
	assert.equal(competencyOutline(graph, '#4361EE').filter((row) => row.node.id === 3).length, 1);
});
