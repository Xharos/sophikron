/** Damped spring motion shared by the renderer and deterministic interaction tests. */
export interface FloatingNode {
	x: number;
	y: number;
	vx: number;
	vy: number;
	pinned: boolean;
}

export interface CollisionBody {
	id: number;
	state: FloatingNode;
	width: number;
	height: number;
}

/** Apply transient magnetic impulses without blocking the spring's route home. */
export function resolveCollisions(bodies: CollisionBody[], strength = 1, delta = 1 / 60): void {
	if (strength < 0.001) return;
	for (let i = 0; i < bodies.length; i++)
		for (let j = i + 1; j < bodies.length; j++) {
			const a = bodies[i],
				b = bodies[j],
				dx = b.state.x - a.state.x,
				dy = b.state.y - a.state.y;
			const rx = (a.width + b.width) / 2 + 40,
				ry = (a.height + b.height) / 2 + 32;
			const distance = Math.hypot(dx / rx, dy / ry);
			if (distance >= 1.4) continue;
			const length = Math.hypot(dx, dy) || 1;
			const nx = length === 1 && !dx && !dy ? 1 : dx / length,
				ny = dy / length;
			const force = (1.4 - distance) * 1450 * strength * Math.min(delta, 0.032);
			// The tangential component breaks head-on symmetry so two nodes can pass.
			const side = a.id < b.id ? 1 : -1;
			if (!a.state.pinned) {
				a.state.vx -= (nx - ny * 0.5 * side) * force;
				a.state.vy -= (ny + nx * 0.5 * side) * force;
			}
			if (!b.state.pinned) {
				b.state.vx += (nx - ny * 0.5 * side) * force;
				b.state.vy += (ny + nx * 0.5 * side) * force;
			}
		}
}

/** Return towards the layout anchor with a small, deterministic water-like drift. */
export function stepFloatingNode(
	node: FloatingNode,
	anchor: { x: number; y: number; id: number },
	seconds: number,
	delta: number,
	reduced: boolean
): void {
	if (node.pinned) return;
	if (reduced) {
		node.x = anchor.x;
		node.y = anchor.y;
		node.vx = 0;
		node.vy = 0;
		return;
	}
	const dt = Math.min(0.032, Math.max(0, delta));
	const x = anchor.x + Math.sin(seconds * 0.65 + anchor.id * 1.7) * 3.5;
	const y = anchor.y + Math.cos(seconds * 0.55 + anchor.id * 1.3) * 3.5;
	node.vx += ((x - node.x) * 12 - node.vx * 6) * dt;
	node.vy += ((y - node.y) * 12 - node.vy * 6) * dt;
	node.x += node.vx * dt;
	node.y += node.vy * dt;
}
