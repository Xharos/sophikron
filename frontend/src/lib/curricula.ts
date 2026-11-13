/** Portable identities and edges, independent of the visual placement of nodes. */
export interface Curriculum {
	id: number;
	title: string;
	description: string | null;
	source_url: string | null;
	is_active: boolean;
	version: number;
	subject_ids: number[];
}
export interface CurriculumSubject {
	id: number;
	name: string;
	color: string;
	icon: import('./lessons').LessonIcon;
	is_active: boolean;
	can_edit: boolean;
}
export interface CurriculumCatalog {
	can_manage: boolean;
	curricula: Curriculum[];
	subjects: CurriculumSubject[];
}
export interface Competency {
	id: number;
	code: string | null;
	name: string;
	semester: number | null;
	knowledge: string | null;
	comment: string | null;
	color: string | null;
	position: number;
}
export interface CompetencyEdge {
	parent_id: number;
	child_id: number;
}
export interface CompetencyGraph {
	can_undo?: boolean;
	curriculum_id: number;
	subject_id: number;
	version: number;
	nodes: Competency[];
	edges: CompetencyEdge[];
}

/** Preserve the subject name while producing a portable download basename. */
export function competencyFileName(subjectName: string): string {
	let name = subjectName
		.normalize('NFC')
		.replace(/[\p{Cc}<>:"/\\|?*]/gu, '_')
		.trim()
		.replace(/[. ]+$/g, '');
	if (!name) name = 'competences';
	if (/^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(name)) name = `_${name}`;
	return `${name}.json`;
}

/** Send only allowlisted operations through the same-origin server endpoint. */
export async function curriculumRequest<T>(
	command: string,
	data: Record<string, unknown> = {}
): Promise<T> {
	const body = JSON.stringify({ command, ...data });
	if (new TextEncoder().encode(body).length > 16384)
		throw new Error(
			'Le texte dépasse la taille autorisée pour une sauvegarde (16 Ko). Réduisez les connaissances ou le commentaire.'
		);
	const response = await fetch('/curricula/data', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body
	});
	const result = await response.json();
	if (!response.ok) throw new Error(result.message ?? 'La demande a échoué.');
	return result as T;
}

/** Find ancestors iteratively, including every path to a shared competency. */
export function ancestors(id: number, edges: CompetencyEdge[]): Set<number> {
	const found = new Set<number>();
	const pending = [id];
	const parents = new Map<number, number[]>();
	for (const edge of edges)
		parents.set(edge.child_id, [...(parents.get(edge.child_id) ?? []), edge.parent_id]);
	while (pending.length) {
		const current = pending.pop()!;
		if (found.has(current)) continue;
		found.add(current);
		pending.push(...(parents.get(current) ?? []));
	}
	return found;
}

/** Find all descendants once when excluding cyclic parent choices in the editor. */
export function descendants(id: number, edges: CompetencyEdge[]): Set<number> {
	return ancestors(
		id,
		edges.map((edge) => ({ parent_id: edge.child_id, child_id: edge.parent_id }))
	);
}

export interface GraphPoint {
	id: number;
	x: number;
	y: number;
	color: string;
	depth: number;
	orbitX?: number;
	orbitY?: number;
	radius?: number;
	angle?: number;
	parentId?: number;
}

/** Resolve inherited search colors without laying out hidden branches. */
export function competencyColors(graph: CompetencyGraph, fallback: string): Map<number, string> {
	const parents = new Set(graph.edges.map((edge) => edge.child_id));
	const children = new Map<number, number[]>();
	for (const edge of graph.edges)
		children.set(edge.parent_id, [...(children.get(edge.parent_id) ?? []), edge.child_id]);
	const nodes = new Map(graph.nodes.map((node) => [node.id, node]));
	const colors = new Map<number, string>();
	const queue = graph.nodes.filter((node) => !parents.has(node.id)).map((node) => node.id);
	for (const id of queue) colors.set(id, nodes.get(id)?.color ?? fallback);
	for (let i = 0; i < queue.length; i++)
		for (const child of children.get(queue[i]) ?? []) {
			if (colors.has(child)) continue;
			colors.set(child, nodes.get(child)?.color ?? colors.get(queue[i]) ?? fallback);
			queue.push(child);
		}
	return colors;
}

/** Build a compact parent-first outline, displaying shared competencies once. */
export function competencyOutline(
	graph: CompetencyGraph,
	fallback: string
): { node: Competency; depth: number; color: string; parentColor: string }[] {
	const byId = new Map(graph.nodes.map((node) => [node.id, node]));
	const children = new Map<number, number[]>();
	const parented = new Set(graph.edges.map((edge) => edge.child_id));
	const rank = (a: number, b: number): number =>
		compareCodes(byId.get(a)?.code ?? '', byId.get(b)?.code ?? '') ||
		byId.get(a)!.position - byId.get(b)!.position ||
		a - b;
	for (const edge of graph.edges)
		if (byId.has(edge.parent_id) && byId.has(edge.child_id))
			children.set(edge.parent_id, [...(children.get(edge.parent_id) ?? []), edge.child_id]);
	const roots = graph.nodes
		.filter((node) => !parented.has(node.id))
		.map((node) => node.id)
		.sort(rank);
	const entries = new Map<
		number,
		{ node: Competency; depth: number; color: string; parentColor: string }
	>();
	const owned = new Map<number, number[]>();
	const queue = [...roots];
	for (const id of roots) {
		const node = byId.get(id)!;
		entries.set(id, {
			node,
			depth: 0,
			color: node.color ?? fallback,
			parentColor: node.color ?? fallback
		});
	}
	for (let i = 0; i < queue.length; i++)
		for (const id of (children.get(queue[i]) ?? []).sort(rank)) {
			if (entries.has(id)) continue;
			const parent = entries.get(queue[i])!,
				node = byId.get(id)!;
			entries.set(id, {
				node,
				depth: parent.depth + 1,
				color: node.color ?? parent.color,
				parentColor: parent.color
			});
			owned.set(queue[i], [...(owned.get(queue[i]) ?? []), id]);
			queue.push(id);
		}
	const result: ReturnType<typeof competencyOutline> = [],
		pending = [...roots].reverse();
	while (pending.length) {
		const id = pending.pop()!;
		result.push(entries.get(id)!);
		pending.push(...[...(owned.get(id) ?? [])].reverse());
	}
	return result;
}

/** Keep deep levels subordinate without making labels too small or washed out. */
export function competencyAppearance(depth: number): {
	scale: number;
	saturation: number;
	spacing: number;
} {
	const level = Math.max(0, Math.min(3, depth - 1));
	return { scale: 1 - level * 0.06, saturation: 1 - level * 0.12, spacing: level * 10 };
}

/** Compare hierarchical labels by ordinal segments, including Z, AA and numeric siblings. */
export function compareCodes(left: string, right: string): number {
	const ordinal = (part: string): number =>
		/^\d+$/.test(part)
			? Number(part)
			: [...part.toLowerCase()].reduce(
					(value, letter) => value * 26 + letter.charCodeAt(0) - 96,
					0
				);
	const a = left.split('.'),
		b = right.split('.');
	for (let i = 0; i < Math.min(a.length, b.length); i++) {
		const difference = ordinal(a[i]) - ordinal(b[i]);
		if (difference) return difference;
	}
	return a.length - b.length;
}

/** Rebalance visible branches on concentric rings using actual rectangle separation. */
export function layoutGraph(
	graph: CompetencyGraph,
	expanded: Set<number>,
	fallback: string,
	aspect = 1.5
): GraphPoint[] {
	const children = new Map<number, number[]>();
	const parented = new Set(graph.edges.map((e) => e.child_id));
	for (const edge of graph.edges)
		children.set(edge.parent_id, [...(children.get(edge.parent_id) ?? []), edge.child_id]);
	const nodes = new Map(graph.nodes.map((n) => [n.id, n]));
	const rank = (a: Competency, b: Competency): number =>
		a.code && b.code ? compareCodes(a.code, b.code) : a.position - b.position || a.id - b.id;
	const roots = graph.nodes.filter((n) => !parented.has(n.id)).sort(rank);
	const visible = new Map<number, { depth: number; color: string }>();
	const branches = new Map<number, number[]>();
	const queue = roots.map((node) => node.id);
	for (const root of roots) visible.set(root.id, { depth: 0, color: root.color ?? fallback });
	// Breadth-first ownership keeps shared nodes unique and avoids recursive depth limits.
	for (let index = 0; index < queue.length; index++) {
		const id = queue[index],
			parent = visible.get(id)!;
		if (!expanded.has(id)) continue;
		const branch = (children.get(id) ?? [])
			.filter((child) => nodes.has(child))
			.sort((a, b) => rank(nodes.get(a)!, nodes.get(b)!));
		for (const child of branch) {
			if (visible.has(child)) continue;
			visible.set(child, {
				depth: parent.depth + 1,
				color: nodes.get(child)!.color ?? parent.color
			});
			branches.set(id, [...(branches.get(id) ?? []), child]);
			queue.push(child);
		}
	}
	const size = (id: number): { width: number; height: number } => {
		const scale = competencyAppearance(visible.get(id)?.depth ?? 0).scale;
		return id < 0 ? { width: 205, height: 80 } : { width: 142 * scale, height: 60 * scale };
	};

	const clusters = roots.map((root) => {
		const ids: number[] = [root.id],
			parents = new Map<number, number>();
		for (let i = 0; i < ids.length; i++)
			for (const child of branches.get(ids[i]) ?? []) {
				parents.set(child, ids[i]);
				ids.push(child);
			}
		const rings = new Map<number, number[]>();
		for (const id of ids) {
			const depth = visible.get(id)!.depth;
			rings.set(depth, [...(rings.get(depth) ?? []), id]);
		}
		const deepest = Math.max(...rings.keys());
		const radii = Array.from({ length: deepest + 1 }, (_, depth) => (depth ? depth * 170 + 20 : 0));
		const angles = new Map<number, number>(ids.map((id) => [id, -Math.PI / 2]));
		const demand = new Map<number, number>();
		const assignAngles = (): void => {
			for (const id of [...ids].reverse()) {
				const depth = visible.get(id)!.depth,
					angle = angles.get(id)!,
					box = size(id);
				const own =
					(Math.min(
						box.width / Math.max(0.001, Math.abs(Math.sin(angle))),
						box.height / Math.max(0.001, Math.abs(Math.cos(angle)))
					) +
						22) /
					Math.max(1, radii[depth]);
				demand.set(
					id,
					Math.max(
						own,
						(branches.get(id) ?? []).reduce((sum, child) => sum + demand.get(child)!, 0)
					)
				);
			}
			const sectors = new Map<number, { start: number; span: number }>([
				[root.id, { start: -Math.PI / 2, span: Math.PI * 2 }]
			]);
			for (const id of ids) {
				const children = branches.get(id) ?? [];
				if (!children.length) continue;
				const sector = sectors.get(id)!;
				const span = id === root.id ? Math.PI * 2 : Math.min(Math.PI, sector.span);
				const shares = new Map<number, number>();
				let available = span,
					active = [...children];
				while (active.length) {
					const total = active.reduce((sum, child) => sum + demand.get(child)!, 0);
					const capped = active.filter(
						(child) => (available * demand.get(child)!) / total > Math.PI && active.length > 1
					);
					if (!capped.length) {
						for (const child of active) shares.set(child, (available * demand.get(child)!) / total);
						break;
					}
					for (const child of capped) {
						shares.set(child, Math.PI);
						available -= Math.PI;
					}
					active = active.filter((child) => !shares.has(child));
				}
				let cursor =
					id === root.id ? -Math.PI / 2 - shares.get(children[0])! / 2 : angles.get(id)! - span / 2;
				for (const child of children) {
					const share = shares.get(child)!;
					angles.set(child, cursor + share / 2);
					sectors.set(child, { start: cursor, span: share });
					cursor += share;
				}
			}
		};
		const fitRings = (): void => {
			for (let depth = 1; depth <= deepest; depth++) {
				const ring = rings.get(depth)!;
				const previous = rings.get(depth - 1)!;
				const diagonal = (id: number): number => Math.hypot(size(id).width, size(id).height) / 2;
				let radius =
					radii[depth - 1] +
					Math.max(...previous.map(diagonal)) +
					Math.max(...ring.map(diagonal)) +
					24;
				// Solve rectangle separation on a circle, without dividing by a shrinking sector.
				const geometry = ring.map((id) => ({
					box: size(id),
					cos: Math.cos(angles.get(id)!),
					sin: Math.sin(angles.get(id)!)
				}));
				for (let i = 0; i < ring.length; i++)
					for (let j = 0; j < i; j++) {
						const a = geometry[i],
							b = geometry[j];
						const dx = Math.abs(a.cos - b.cos),
							dy = Math.abs(a.sin - b.sin);
						radius = Math.max(
							radius,
							Math.min(
								((a.box.width + b.box.width) / 2 + 18) / Math.max(1e-9, dx),
								((a.box.height + b.box.height) / 2 + 18) / Math.max(1e-9, dy)
							)
						);
					}
				radii[depth] = radius;
			}
			// Share crowding between rings instead of leaving one long radial jump.
			for (let depth = deepest - 1; depth >= 1; depth--)
				radii[depth] = Math.max(radii[depth], radii[depth + 1] - 230);
		};
		for (let pass = 0; pass < 12; pass++) {
			assignAngles();
			fitRings();
		}
		const items = ids.map((id) => {
			const depth = visible.get(id)!.depth,
				radius = radii[depth],
				angle = angles.get(id)!;
			return {
				id,
				x: radius * Math.cos(angle),
				y: radius * Math.sin(angle),
				...visible.get(id)!,
				radius,
				angle,
				orbitX: 0,
				orbitY: 0,
				parentId: parents.get(id)
			};
		});
		const left = Math.min(...items.map((p) => p.x - size(p.id).width / 2)),
			top = Math.min(...items.map((p) => p.y - size(p.id).height / 2));
		return {
			items,
			left,
			top,
			width: Math.max(...items.map((p) => p.x + size(p.id).width / 2)) - left,
			height: Math.max(...items.map((p) => p.y + size(p.id).height / 2)) - top
		};
	});

	// Pack subject bounds independently; an expanded subject no longer stretches empty ones.
	const packed: { x: number; y: number; width: number; height: number }[] = [];
	const result = new Map<number, GraphPoint>();
	const ratio = Math.max(0.4, Math.min(3, aspect));
	let width = 0,
		height = 0;
	for (const cluster of clusters.sort((a, b) => b.width * b.height - a.width * a.height)) {
		const candidates = [
			{ x: 0, y: 0 },
			...packed.flatMap((box) => [
				{ x: box.x + box.width + 32, y: box.y },
				{ x: box.x, y: box.y + box.height + 32 }
			]),
			{ x: width + 32, y: 0 },
			{ x: 0, y: height + 32 }
		];
		const best = candidates
			.filter(
				(candidate) =>
					!packed.some(
						(box) =>
							candidate.x < box.x + box.width + 24 &&
							candidate.x + cluster.width + 24 > box.x &&
							candidate.y < box.y + box.height + 24 &&
							candidate.y + cluster.height + 24 > box.y
					)
			)
			.sort((a, b) => {
				const score = (p: { x: number; y: number }): number => {
					const w = Math.max(width, p.x + cluster.width),
						h = Math.max(height, p.y + cluster.height);
					return Math.max(w / ratio, h) ** 2 + w * h * 0.15;
				};
				return score(a) - score(b);
			})[0];
		packed.push({ ...best, width: cluster.width, height: cluster.height });
		for (const point of cluster.items)
			result.set(point.id, {
				...point,
				x: point.x - cluster.left + best.x,
				y: point.y - cluster.top + best.y,
				orbitX: -cluster.left + best.x,
				orbitY: -cluster.top + best.y
			});
		width = Math.max(width, best.x + cluster.width);
		height = Math.max(height, best.y + cluster.height);
	}
	return queue.map((id) => {
		const point = result.get(id)!;
		return {
			...point,
			x: point.x - width / 2,
			y: point.y - height / 2,
			orbitX: (point.orbitX ?? 0) - width / 2,
			orbitY: (point.orbitY ?? 0) - height / 2
		};
	});
}

/** Connect block borders directly, without following the layout rings. */
export function competencyLinkPath(
	parent: GraphPoint,
	child: GraphPoint
): { x: number; y: number }[] {
	const size = (p: GraphPoint): { width: number; height: number } =>
		p.id < 0
			? { width: 205, height: 80 }
			: {
					width: 142 * competencyAppearance(p.depth).scale,
					height: 60 * competencyAppearance(p.depth).scale
				};
	const clip = (node: GraphPoint, towards: GraphPoint): { x: number; y: number } => {
		const dx = towards.x - node.x,
			dy = towards.y - node.y,
			box = size(node);
		const t = Math.min(
			box.width / 2 / Math.max(1e-9, Math.abs(dx)),
			box.height / 2 / Math.max(1e-9, Math.abs(dy)),
			1
		);
		return { x: node.x + dx * t, y: node.y + dy * t };
	};
	return [clip(parent, child), clip(child, parent)];
}

/** Attach subject master nodes to the roots of lazily loaded subject graphs. */
export function programmeScene(
	subjects: CurriculumSubject[],
	graphs: Record<number, CompetencyGraph>
): CompetencyGraph {
	const nodes: Competency[] = [],
		edges: CompetencyEdge[] = [];
	for (const subject of subjects) {
		nodes.push({
			id: -subject.id,
			name: subject.name,
			code: null,
			color: subject.color,
			semester: null,
			knowledge: null,
			comment: null,
			position: subject.id
		});
		const graph = graphs[subject.id];
		if (!graph) continue;
		nodes.push(...graph.nodes);
		edges.push(...graph.edges);
		const parented = new Set(graph.edges.map((e) => e.child_id));
		for (const node of graph.nodes)
			if (!parented.has(node.id)) edges.push({ parent_id: -subject.id, child_id: node.id });
	}
	return { curriculum_id: 0, subject_id: 0, version: 0, nodes, edges };
}
