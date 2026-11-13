<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import * as THREE from 'three';
	import Icon from '../Icon.svelte';
	import SubjectIdentity from '../SubjectIdentity.svelte';
	import {
		ancestors,
		competencyAppearance,
		competencyOutline,
		competencyLinkPath,
		competencyColors,
		layoutGraph,
		programmeScene,
		type CompetencyGraph,
		type Competency,
		type CurriculumSubject,
		type GraphPoint
	} from '#lib/curricula';
	import { resolveCollisions, stepFloatingNode, type FloatingNode } from '#lib/curriculumMotion';
	let {
		graphs,
		subjects,
		pending,
		active,
		expandId,
		onload,
		onopen,
		onadd
	}: {
		graphs: Record<number, CompetencyGraph>;
		subjects: CurriculumSubject[];
		pending: number[];
		active: boolean;
		expandId?: number;
		onload: (id: number) => void;
		onopen: (subjectId: number, node: Competency) => void;
		onadd: (subjectId: number, parentId?: number) => void;
	} = $props();
	let expanded = $state(new Set<number>()),
		query = $state(''),
		textView = $state(false),
		webglError = $state(''),
		ready = $state(false);
	let host: HTMLDivElement;
	let canvas = $state<HTMLCanvasElement>();
	let mobile = $state(false),
		mounted = $state(false);
	const showText = $derived(mobile || textView);
	onMount(() => {
		const query = matchMedia('(max-width: 650px)');
		const update = (): void => {
			mobile = query.matches;
			if (mobile && document.fullscreenElement === host)
				void document.exitFullscreen().catch(() => {});
		};
		update();
		mounted = true;
		query.addEventListener('change', update);
		return () => query.removeEventListener('change', update);
	});
	let highlighted = $state(new Set<number>());
	let highlightTimer: ReturnType<typeof setTimeout> | undefined;
	let repulsion = 0;
	let hiddenSubjects = $state(new Set<number>());
	let reducedMotion = $state(false);
	let fullscreen = $state(false),
		fullscreenError = $state('');
	onMount(() => {
		const update = (): void => {
			fullscreen = document.fullscreenElement === host;
			autoFrame = true;
			fit();
		};
		document.addEventListener('fullscreenchange', update);
		return () => document.removeEventListener('fullscreenchange', update);
	});
	async function toggleFullscreen(): Promise<void> {
		fullscreenError = '';
		try {
			if (document.fullscreenElement === host) await document.exitFullscreen();
			else await host.requestFullscreen();
		} catch {
			fullscreenError = 'Le changement de mode plein écran est indisponible.';
		}
	}
	let viewportAspect = $state(1.5);
	const visibleSubjects = $derived(subjects.filter((subject) => !hiddenSubjects.has(subject.id)));
	const sceneGraph = $derived(programmeScene(visibleSubjects, graphs));
	const nodes = $derived(
		new Map(programmeScene(subjects, graphs).nodes.map((node) => [node.id, node]))
	);
	const ownership = $derived(
		new Map(
			Object.values(graphs).flatMap((graph) =>
				graph.nodes.map((node) => [node.id, graph.subject_id] as const)
			)
		)
	);
	const layout = $derived(
		mobile ? [] : layoutGraph(sceneGraph, expanded, '#4361EE', viewportAspect)
	);
	const layoutPoints = $derived(new Map(layout.map((point) => [point.id, point])));
	const searchColors = $derived(competencyColors(sceneGraph, '#4361EE'));
	const matches = $derived(
		query.trim()
			? sceneGraph.nodes
					.filter((node) =>
						`${node.code ?? ''} ${node.name}`
							.toLocaleLowerCase('fr')
							.includes(query.trim().toLocaleLowerCase('fr'))
					)
					.slice(0, 20)
			: []
	);
	// These renderer-owned caches intentionally do not trigger Svelte effects per frame.
	// eslint-disable-next-line svelte/prefer-svelte-reactivity
	const labels = new Map<number, HTMLDivElement>();
	// eslint-disable-next-line svelte/prefer-svelte-reactivity
	const motion = new Map<number, FloatingNode>();
	// Transition painters follow the live camera rather than freezing screen coordinates.
	// eslint-disable-next-line svelte/prefer-svelte-reactivity
	const transitionPainters = new Map<HTMLElement, () => void>();
	let renderer: THREE.WebGLRenderer | undefined,
		scene: THREE.Scene,
		camera: THREE.OrthographicCamera,
		group: THREE.Group;
	let points: { mesh: THREE.Mesh; anchor: GraphPoint }[] = [];
	let links: { mesh: THREE.Line; parent: number; child: number; dot: THREE.Mesh }[] = [];
	let frame = 0,
		width = 1000,
		height = 700,
		zoom = 1,
		targetZoom = 1,
		panX = 0,
		panY = 0,
		targetPanX = 0,
		targetPanY = 0;
	let autoFrame = true,
		suppressClickUntil = 0;
	let wake = (): void => {},
		fit = (): void => {};
	function centerOnSpace(event: KeyboardEvent): void {
		if (
			event.code !== 'Space' ||
			event.repeat ||
			event.altKey ||
			event.ctrlKey ||
			event.metaKey ||
			showText ||
			document.querySelector('dialog[open]')
		)
			return;
		if (
			event.target instanceof Element &&
			(event.target.closest('input,textarea,select,[contenteditable="true"],[role="textbox"]') ||
				(event.target.closest('button,a') && !host.contains(event.target)))
		)
			return;
		event.preventDefault();
		autoFrame = true;
		fit();
	}
	function toggleSubject(id: number): void {
		hiddenSubjects = hiddenSubjects.has(id)
			? new Set([...hiddenSubjects].filter((value) => value !== id))
			: new Set([...hiddenSubjects, id]);
		autoFrame = true;
	}
	function toggle(id: number): void {
		if (performance.now() < suppressClickUntil) return;
		autoFrame = true;
		expanded = expanded.has(id)
			? new Set([...expanded].filter((value) => value !== id))
			: new Set([...expanded, id]);
		if (id < 0 && expanded.has(id)) onload(-id);
	}
	function open(id: number): void {
		if (performance.now() < suppressClickUntil || id < 0) return;
		const subjectId = ownership.get(id),
			node = nodes.get(id);
		if (subjectId && node) onopen(subjectId, node);
	}
	function reveal(id: number): void {
		highlighted = ancestors(id, sceneGraph.edges);
		clearTimeout(highlightTimer);
		highlightTimer = setTimeout(() => (highlighted = new Set()), 10000);
		expanded = new Set([...expanded, ...ancestors(id, sceneGraph.edges)]);
		query = '';
		autoFrame = true;
		if (id < 0) onload(-id);
	}
	function addUnder(subjectId: number, parentId?: number): void {
		autoFrame = true;
		expanded = new Set([...expanded, parentId ?? -subjectId]);
		onadd(subjectId, parentId);
	}
	$effect(() => {
		if (expandId && nodes.has(expandId)) {
			const path = ancestors(expandId, sceneGraph.edges);
			untrack(() => {
				expanded = new Set([...expanded, ...path]);
			});
		}
	});
	function clear(): void {
		if (!group) return;
		for (const object of [...group.children]) {
			if (object instanceof THREE.Mesh || object instanceof THREE.Line) {
				object.geometry.dispose();
				(Array.isArray(object.material) ? object.material : [object.material]).forEach((material) =>
					material.dispose()
				);
			}
			group.remove(object);
		}
		points = [];
		links = [];
	}
	function trackLabel(element: HTMLDivElement, id: number): { destroy: () => void } {
		labels.set(id, element);
		return {
			destroy: () => {
				if (labels.get(id) === element) labels.delete(id);
				transitionPainters.delete(element);
			}
		};
	}
	function absorb(
		element: HTMLElement,
		options: { id: number }
	): { duration: number; tick: (t: number) => void } {
		const all = programmeScene(subjects, graphs),
			visible = new Set(layout.map((p) => p.id));
		let parent = all.edges.find((edge) => edge.child_id === options.id)?.parent_id;
		// Transient traversal state, not component state.
		// eslint-disable-next-line svelte/prefer-svelte-reactivity
		const visited = new Set<number>();
		while (parent !== undefined && !visible.has(parent) && !visited.has(parent)) {
			visited.add(parent);
			parent = all.edges.find((edge) => edge.child_id === parent)?.parent_id;
		}
		let incoming = layoutPoints.has(options.id);
		let source = { ...motion.get(options.id) };
		let progress = incoming ? 0 : 1;
		const paint = (): void => {
			const target = layoutPoints.get(options.id);
			if (!!target !== incoming) {
				incoming = !!target;
				source = { ...motion.get(options.id) };
			}
			const ancestor = parent !== undefined ? motion.get(parent) : undefined;
			const current = target ? (motion.get(options.id) ?? target) : undefined;
			const x =
				current?.x ??
				(ancestor?.x ?? source.x ?? 0) +
					((source.x ?? 0) - (ancestor?.x ?? source.x ?? 0)) * progress;
			const y =
				current?.y ??
				(ancestor?.y ?? source.y ?? 0) +
					((source.y ?? 0) - (ancestor?.y ?? source.y ?? 0)) * progress;
			element.style.opacity = String(progress);
			const scale = competencyAppearance(target?.depth ?? Number(element.dataset.depth ?? 0)).scale;
			element.style.transform = `translate(${width / 2 + x * zoom + panX}px,${height / 2 + y * zoom + panY}px) scale(${zoom * scale * (0.15 + 0.85 * progress)}) translate(-50%,-50%)`;
		};
		const duration = reducedMotion || parent === undefined ? 0 : 380;
		if (duration) transitionPainters.set(element, paint);
		else {
			progress = incoming ? 1 : 0;
			paint();
		}
		return {
			duration,
			tick: (t) => {
				progress = t;
				paint();
				if ((incoming && t === 1) || (!incoming && t === 0)) transitionPainters.delete(element);
			}
		};
	}
	$effect(() => {
		const anchors = layout,
			graph = sceneGraph;
		if (!ready) return;
		const previouslyVisible = new Set(points.map(({ anchor }) => anchor.id));
		clear();
		for (const anchor of anchors) {
			if (!motion.has(anchor.id) || !previouslyVisible.has(anchor.id)) {
				const parentId = graph.edges.find((edge) => edge.child_id === anchor.id)?.parent_id;
				const parent = parentId !== undefined ? motion.get(parentId) : undefined;
				motion.set(anchor.id, {
					x: parent?.x ?? anchor.x,
					y: parent?.y ?? anchor.y,
					vx: 0,
					vy: 0,
					pinned: false
				});
			}
			const mesh = new THREE.Mesh(
				new THREE.CircleGeometry(anchor.id < 0 ? 8 : 4, 20),
				new THREE.MeshBasicMaterial({ color: anchor.color })
			);
			group.add(mesh);
			points.push({ mesh, anchor });
		}
		const visible = new Set(anchors.map((point) => point.id));
		for (const edge of graph.edges.filter(
			(edge) => visible.has(edge.parent_id) && visible.has(edge.child_id)
		)) {
			const color = anchors.find((point) => point.id === edge.child_id)?.color ?? '#4361EE';
			const mesh = new THREE.Line(
				new THREE.BufferGeometry().setFromPoints(
					Array.from({ length: 2 }, () => new THREE.Vector3())
				),
				new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.3 })
			);
			const dot = new THREE.Mesh(
				new THREE.CircleGeometry(1.8, 10),
				new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.7 })
			);
			group.add(mesh, dot);
			links.push({ mesh, dot, parent: edge.parent_id, child: edge.child_id });
		}
		for (const id of motion.keys()) if (!nodes.has(id)) motion.delete(id);
		if (autoFrame) fit();
		wake();
	});
	$effect(() => {
		if (!mounted || mobile || !canvas) return;
		const reduced = matchMedia('(prefers-reduced-motion: reduce)');
		reducedMotion = reduced.matches;
		try {
			renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
			webglError = '';
		} catch {
			webglError = 'WebGL est indisponible. Utilisez la vue textuelle.';
			textView = true;
			return;
		}
		renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
		scene = new THREE.Scene();
		camera = new THREE.OrthographicCamera();
		camera.position.z = 100;
		group = new THREE.Group();
		scene.add(group);
		ready = true;
		let previousTime = 0;
		let drag: {
			id: number | null;
			startX: number;
			startY: number;
			x: number;
			y: number;
			moved: boolean;
			pointer: number;
		} | null = null;
		const draw = (now: number): void => {
			if (!renderer || document.hidden || showText) {
				frame = 0;
				return;
			}
			const dt = previousTime ? Math.min(0.032, (now - previousTime) / 1000) : 1 / 60;
			previousTime = now;
			const ease = reduced.matches ? 1 : 1 - Math.exp(-dt * 12);
			zoom += (targetZoom - zoom) * ease;
			panX += (targetPanX - panX) * ease;
			panY += (targetPanY - panY) * ease;
			camera.left = -width / (2 * zoom);
			camera.right = width / (2 * zoom);
			camera.top = height / (2 * zoom);
			camera.bottom = -height / (2 * zoom);
			camera.position.x = -panX / zoom;
			camera.position.y = panY / zoom;
			camera.updateProjectionMatrix();
			let moving =
				Math.abs(targetZoom - zoom) > 0.001 ||
				Math.abs(targetPanX - panX) + Math.abs(targetPanY - panY) > 0.1;
			for (const { anchor } of points) {
				const state = motion.get(anchor.id)!;
				stepFloatingNode(state, anchor, now / 1000, dt, reduced.matches);
				moving ||= Math.abs(state.vx) + Math.abs(state.vy) > 0.1;
			}
			const labelScale = zoom;
			if (!drag) repulsion *= Math.exp(-dt * 2.5);
			resolveCollisions(
				points.map(({ anchor }) => ({
					id: anchor.id,
					state: motion.get(anchor.id)!,
					width:
						((labels.get(anchor.id)?.offsetWidth ?? 150) *
							labelScale *
							competencyAppearance(anchor.depth).scale) /
						zoom,
					height:
						((labels.get(anchor.id)?.offsetHeight ?? 60) *
							labelScale *
							competencyAppearance(anchor.depth).scale) /
						zoom
				})),
				repulsion,
				dt
			);
			for (const { mesh, anchor } of points) {
				const state = motion.get(anchor.id)!;
				mesh.position.set(state.x, -state.y, 0);
				const label = labels.get(anchor.id);
				if (label) {
					label.style.opacity = '1';
					label.style.transform = `translate(${width / 2 + state.x * zoom + panX}px, ${height / 2 + state.y * zoom + panY}px) scale(${zoom * competencyAppearance(anchor.depth).scale}) translate(-50%, -50%)`;
				}
			}
			for (const paint of transitionPainters.values()) paint();
			for (const { mesh, dot, parent, child } of links) {
				const lit = highlighted.has(parent) && highlighted.has(child);
				(mesh.material as THREE.LineBasicMaterial).opacity = lit ? 0.95 : 0.3;
				dot.scale.setScalar(lit ? 2.3 : 1);
				const a = motion.get(parent)!,
					b = motion.get(child)!;
				const attribute = mesh.geometry.getAttribute('position') as THREE.BufferAttribute;

				const path = competencyLinkPath(
					{ ...layoutPoints.get(parent)!, x: a.x, y: a.y },
					{ ...layoutPoints.get(child)!, x: b.x, y: b.y }
				);
				for (let i = 0; i < 2; i++) {
					const point = path[Math.min(i, path.length - 1)];
					attribute.setXYZ(i, point.x, -point.y, -1);
				}
				attribute.needsUpdate = true;
				mesh.geometry.computeBoundingSphere();
				const lengths = path
					.slice(1)
					.map((point, i) => Math.hypot(point.x - path[i].x, point.y - path[i].y));
				let remaining =
					lengths.reduce((sum, length) => sum + length, 0) *
					((now / (lit ? 1100 : 4500) + child * 0.173) % 1);
				let segment = 0;
				while (segment < lengths.length - 1 && remaining > lengths[segment])
					remaining -= lengths[segment++];
				const t = lengths[segment] ? remaining / lengths[segment] : 0,
					start = path[segment],
					end = path[segment + 1];
				dot.visible = !reduced.matches;
				dot.position.set(start.x + (end.x - start.x) * t, -start.y - (end.y - start.y) * t, 0);
			}
			host.dataset.zoom = zoom.toFixed(3);
			host.dataset.panX = panX.toFixed(1);
			host.dataset.panY = panY.toFixed(1);
			renderer.render(scene, camera);
			frame = !reduced.matches || moving || drag ? requestAnimationFrame(draw) : 0;
		};
		wake = () => {
			if (!frame && !document.hidden && !showText) {
				previousTime = 0;
				frame = requestAnimationFrame(draw);
			}
		};
		fit = () => {
			const current = layout;
			if (!current.length || width < 1 || height < 1) return;
			const minX = Math.min(...current.map((p) => p.x)) - 120,
				maxX = Math.max(...current.map((p) => p.x)) + 120;
			const minY = Math.min(...current.map((p) => p.y)) - 65,
				maxY = Math.max(...current.map((p) => p.y)) + 65;
			targetZoom = Math.max(
				0.15,
				Math.min(3.5, (width - 60) / (maxX - minX), (height - 70) / (maxY - minY))
			);
			targetPanX = (-(minX + maxX) / 2) * targetZoom;
			targetPanY = (-(minY + maxY) / 2) * targetZoom;
			wake();
		};
		const resize = new ResizeObserver(() => {
			if (!host.clientWidth || !host.clientHeight) return;
			width = host.clientWidth;
			height = host.clientHeight;
			viewportAspect = width / height;
			renderer?.setSize(width, height);
			if (autoFrame) fit();
			wake();
		});
		resize.observe(host);
		const down = (event: PointerEvent): void => {
			if (
				event.button !== 0 ||
				!(event.target instanceof Element) ||
				event.target.closest('[data-control]')
			)
				return;
			const label = event.target.closest<HTMLElement>('[data-node-id]');
			drag = {
				id: label ? Number(label.dataset.nodeId) : null,
				startX: event.clientX,
				startY: event.clientY,
				x: event.clientX,
				y: event.clientY,
				moved: false,
				pointer: event.pointerId
			};
		};
		const move = (event: PointerEvent): void => {
			if (!drag || event.pointerId !== drag.pointer) return;
			if (!drag.moved && Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) < 4)
				return;
			drag.moved = true;
			host.setPointerCapture(event.pointerId);
			autoFrame = false;
			const dx = event.clientX - drag.x,
				dy = event.clientY - drag.y;
			if (drag.id !== null) {
				repulsion = 1;
				const state = motion.get(drag.id);
				if (state) {
					state.pinned = true;
					state.x += dx / zoom;
					state.y += dy / zoom;
					state.vx = (dx / zoom) * 8;
					state.vy = (dy / zoom) * 8;
				}
			} else {
				targetPanX += dx;
				targetPanY += dy;
			}
			drag.x = event.clientX;
			drag.y = event.clientY;
			wake();
		};
		const up = (): void => {
			if (!drag) return;
			if (drag.moved) suppressClickUntil = performance.now() + 250;
			if (drag.id !== null) {
				const state = motion.get(drag.id);
				if (state) state.pinned = false;
			}
			if (host.hasPointerCapture(drag.pointer)) host.releasePointerCapture(drag.pointer);
			drag = null;
			wake();
		};
		const wheel = (event: WheelEvent): void => {
			if ((event.target as Element).closest('[data-control]')) return;
			event.preventDefault();
			autoFrame = false;
			const rect = host.getBoundingClientRect(),
				x = event.clientX - rect.left - width / 2,
				y = event.clientY - rect.top - height / 2;
			const next = Math.max(
				0.12,
				Math.min(
					3.5,
					targetZoom * Math.exp(-event.deltaY * (event.deltaMode === 1 ? 16 : 1) * 0.0015)
				)
			);
			targetPanX = x - ((x - targetPanX) * next) / targetZoom;
			targetPanY = y - ((y - targetPanY) * next) / targetZoom;
			targetZoom = next;
			wake();
		};
		const visibility = (): void => {
			if (document.hidden) {
				cancelAnimationFrame(frame);
				frame = 0;
			} else wake();
		};
		host.addEventListener('pointerdown', down);
		host.addEventListener('pointermove', move);
		host.addEventListener('pointerup', up);
		host.addEventListener('pointercancel', up);
		host.addEventListener('wheel', wheel, { passive: false });
		document.addEventListener('visibilitychange', visibility);
		const motionPreference = (): void => {
			reducedMotion = reduced.matches;
			wake();
		};
		reduced.addEventListener('change', motionPreference);
		return () => {
			clearTimeout(highlightTimer);
			cancelAnimationFrame(frame);
			frame = 0;
			resize.disconnect();
			clear();
			transitionPainters.clear();
			renderer?.dispose();
			renderer?.forceContextLoss();
			renderer = undefined;
			ready = false;
			host.removeEventListener('pointerdown', down);
			host.removeEventListener('pointermove', move);
			host.removeEventListener('pointerup', up);
			host.removeEventListener('pointercancel', up);
			host.removeEventListener('wheel', wheel);
			document.removeEventListener('visibilitychange', visibility);
			reduced.removeEventListener('change', motionPreference);
		};
	});
	$effect(() => {
		if (!showText) wake();
	});
	function zoomBy(factor: number): void {
		autoFrame = false;
		targetZoom = Math.max(0.12, Math.min(3.5, targetZoom * factor));
		wake();
	}
</script>

<svelte:window onkeydown={centerOnSpace} />
<div class="subject-filters" aria-label="Matières visibles">
	{#each subjects as subject (subject.id)}<div
			class="subject-filter"
			style:--subject-color={subject.color}
		>
			<button
				aria-pressed={!hiddenSubjects.has(subject.id)}
				aria-label={`${hiddenSubjects.has(subject.id) ? 'Afficher' : 'Masquer'} ${subject.name}`}
				onclick={() => toggleSubject(subject.id)}
				><Icon name={subject.icon} size={13} />{subject.name}</button
			><button
				aria-label={`Isoler ${subject.name}`}
				title="Afficher uniquement cette matière"
				onclick={() => {
					hiddenSubjects = new Set(
						subjects.filter((item) => item.id !== subject.id).map((item) => item.id)
					);
					autoFrame = true;
					onload(subject.id);
					expanded = new Set([...expanded, -subject.id]);
				}}>◎</button
			>
		</div>{/each}
	{#if hiddenSubjects.size}<button
			class="show-all"
			onclick={() => {
				hiddenSubjects = new Set();
				autoFrame = true;
			}}>Tout afficher</button
		>{/if}
</div>

{#if webglError}<p class="notification is-warning is-light" role="status">{webglError}</p>{/if}
{#if fullscreenError}<p class="notification is-warning is-light" role="status">
		{fullscreenError}
	</p>{/if}
<div
	class="graph-space"
	class:text-mode={showText}
	bind:this={host}
	aria-label="Graphe du référentiel"
>
	{#key mobile}<canvas bind:this={canvas} aria-hidden="true"></canvas>{/key}
	<div class="graph-tools" data-control>
		<div class="graph-search">
			<Icon name="search" size={13} /><input
				aria-label="Rechercher une compétence"
				placeholder="Rechercher…"
				bind:value={query}
				onfocus={() => subjects.forEach((s) => onload(s.id))}
			/>
		</div>
		{#if query.trim()}<div class="search-results">
				{#each matches as node (node.id)}<button
						style:--result-color={searchColors.get(node.id) ?? '#4361EE'}
						onclick={() => reveal(node.id)}
						><span class="result-dot" aria-hidden="true"></span><span
							>{node.code ?? ''}
							{node.name}<small
								>{subjects.find((s) => s.id === (node.id < 0 ? -node.id : ownership.get(node.id)))
									?.name}</small
							></span
						></button
					>{:else}<span class="muted">Aucun résultat</span>{/each}
			</div>{/if}
	</div>
	<div class="graph-controls" data-control>
		<button class="icon-button" aria-label="Zoom avant" onclick={() => zoomBy(1.2)}
			><Icon name="plus" size={13} /></button
		><button class="icon-button" aria-label="Zoom arrière" onclick={() => zoomBy(1 / 1.2)}>−</button
		><button
			class="button is-light is-small"
			onclick={() => {
				autoFrame = true;
				fit();
			}}>Recentrer</button
		><button
			class="button is-light is-small"
			aria-pressed={fullscreen}
			onclick={() => {
				void toggleFullscreen();
			}}>{fullscreen ? 'Quitter le plein écran' : 'Plein écran'}</button
		>
	</div>
	{#each layout as point (point.id)}{@const node = nodes.get(point.id)!}{@const subject =
			point.id < 0
				? subjects.find((s) => s.id === -point.id)!
				: subjects.find((s) => s.id === ownership.get(point.id))!}{@const childCount =
			sceneGraph.edges.filter((edge) => edge.parent_id === point.id).length}
		<div
			class="graph-label"
			transition:absorb={{ id: point.id }}
			class:highlighted={highlighted.has(point.id)}
			class:master={point.id < 0}
			style:--node-color={point.color}
			style:--node-saturation={competencyAppearance(point.depth).saturation}
			data-depth={point.depth}
			data-node-id={point.id}
			use:trackLabel={point.id}
		>
			{#if point.id < 0}<button
					class="master-title"
					onclick={() => toggle(point.id)}
					aria-expanded={expanded.has(point.id)}><SubjectIdentity {subject} /></button
				>
			{:else}<button
					class="node-title"
					title={`${node.code ?? ''} ${node.name}`}
					onclick={() => (childCount ? toggle(point.id) : open(point.id))}
					aria-expanded={childCount ? expanded.has(point.id) : undefined}
					>{#if node.code}<strong class="node-code">{node.code}</strong>{/if}<span>{node.name}</span
					>{#if node.semester}<small>S{node.semester}</small>{/if}</button
				>{/if}
			<div class="node-actions" data-control>
				<button
					class="branch-toggle"
					aria-label={`${expanded.has(point.id) ? 'Replier' : 'Déplier'} ${node.name}`}
					onclick={() => toggle(point.id)}
					aria-expanded={expanded.has(point.id)}
					class:expanded={expanded.has(point.id)}
					>{expanded.has(point.id) ? '−' : '+'}{#if point.id < 0}<span title="Enfants directs"
							>{graphs[-point.id] ? childCount : '…'}</span
						>{:else if childCount}<span>{childCount}</span>{/if}</button
				>
				{#if point.id < 0 && pending.includes(-point.id)}<span class="loader"></span>{/if}
				{#if point.id > 0}<button
						aria-label={`Détails de ${node.name}`}
						onclick={() => open(point.id)}><Icon name="edit" size={11} /></button
					>{/if}
				{#if active && subject.can_edit && subject.is_active}<button
						aria-label={`Ajouter sous ${node.name}`}
						onclick={() => addUnder(subject.id, point.id > 0 ? point.id : undefined)}
						><Icon name="plus" size={11} /></button
					>{/if}
			</div>
		</div>
	{/each}
	<div class="graph-caption" data-control>
		<span>Molette : zoom · Glisser : déplacer · Relâcher un nœud : retour en douceur</span><button
			onclick={() => (expanded = new Set())}>Tout replier</button
		><button
			onclick={() => {
				textView = true;
				if (fullscreen) void document.exitFullscreen().catch(() => {});
			}}>Vue textuelle</button
		>
	</div>
</div>
{#if showText}<section class="text-nodes">
		{#if !mobile}<button
				class="button is-light is-small mb-3"
				onclick={() => (textView = false)}
				disabled={!!webglError}>Vue graphique</button
			>{/if}{#each visibleSubjects as subject (subject.id)}<div class="text-subject">
				<h3>
					{#if active && subject.can_edit && subject.is_active}<button
							class="button is-light"
							title={`Ajouter une compétence en ${subject.name}`}
							onclick={() => onadd(subject.id)}><SubjectIdentity {subject} /></button
						>
					{:else}<SubjectIdentity {subject} />{/if}
				</h3>
			</div>
			<ol class="competency-outline" aria-label={`Sommaire de ${subject.name}`}>
				{#each graphs[subject.id] ? competencyOutline(graphs[subject.id], subject.color) : [] as entry (entry.node.id)}{@const node =
						entry.node}
					<li style:--indent={Math.min(entry.depth, 12)} data-depth={entry.depth}>
						<button
							class="text-node"
							style:--outline-color={entry.color}
							style:--parent-color={entry.parentColor}
							onclick={() => onopen(subject.id, node)}
							><span class="is-sr-only">Niveau {entry.depth + 1} : </span><strong
								>{node.code ?? ''}</strong
							><span>{node.name}</span>{#if node.semester}<small>S{node.semester}</small
								>{/if}</button
						>
					</li>{/each}
			</ol>{/each}
	</section>{/if}

<style>
	.result-dot {
		width: 0.6rem;
		height: 0.6rem;
		border-radius: 50%;
		background: var(--result-color);
		flex-shrink: 0;
	}
	.search-results button {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		border-left: 3px solid var(--result-color);
	}
	.search-results small {
		display: block;
		color: var(--color-muted);
		font-size: 0.65rem;
	}
	.graph-label.highlighted {
		outline: 2px solid var(--node-color);
		box-shadow: 0 0 22px color-mix(in srgb, var(--node-color) 65%, transparent);
	}
	.subject-filters {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.4rem;
		margin-bottom: 0.5rem;
	}
	.subject-filter {
		display: flex;
		border: 1px solid color-mix(in srgb, var(--subject-color) 45%, var(--color-border));
		border-radius: 0.6rem;
		overflow: hidden;
	}
	.subject-filter button {
		display: flex;
		gap: 0.4rem;
		align-items: center;
		padding: 0.3rem 0.5rem;
		background: var(--color-surface);
		color: var(--color-muted);
		border: 0;
		font: inherit;
		font-size: 0.7rem;
		cursor: pointer;
	}
	.subject-filter button[aria-pressed='true'] {
		background: color-mix(in srgb, var(--subject-color) 13%, var(--color-surface));
		color: var(--color-ink);
	}
	.show-all {
		border: 0;
		background: transparent;
		color: var(--color-primary);
		font-size: 0.7rem;
		cursor: pointer;
	}
	.branch-toggle {
		transition:
			background-color 0.18s,
			transform 0.18s;
	}
	.branch-toggle:active {
		transform: scale(0.85);
	}
	.branch-toggle.expanded {
		background: color-mix(in srgb, var(--node-color) 25%, var(--color-surface));
	}
	@media (prefers-reduced-motion: reduce) {
		.branch-toggle {
			transition: none;
		}
	}
	.graph-space {
		position: relative;
		width: 100%;
		height: calc(100dvh - 155px);
		min-height: 520px;
		overflow: hidden;
		isolation: isolate;
		touch-action: none;
		border: var(--border-thin);
		border-radius: 0.8rem;
		background:
			radial-gradient(
					circle,
					color-mix(in srgb, var(--color-primary) 18%, transparent) 1px,
					transparent 1.5px
				)
				0 0 / 120px 120px,
			linear-gradient(color-mix(in srgb, var(--color-primary) 4%, transparent) 1px, transparent 1px)
				0 0 / 24px 24px,
			linear-gradient(
					90deg,
					color-mix(in srgb, var(--color-primary) 4%, transparent) 1px,
					transparent 1px
				)
				0 0 / 24px 24px,
			radial-gradient(ellipse at center, var(--color-soft), transparent 75%),
			var(--color-surface);
		cursor: grab;
	}
	.graph-space:active {
		cursor: grabbing;
	}
	.graph-space:fullscreen {
		height: 100dvh;
		border-radius: 0;
	}
	canvas {
		position: absolute;
		inset: 0;
		z-index: 0;
		width: 100%;
		height: 100%;
	}
	.graph-tools {
		position: absolute;
		z-index: 3;
		top: 0.7rem;
		left: 0.7rem;
	}
	.graph-search {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		width: 180px;
		padding: 0.35rem 0.6rem;
		border: var(--border-thin);
		border-radius: 2rem;
		background: var(--color-surface);
	}
	.graph-search input {
		width: 100%;
		min-width: 0;
		background: transparent;
		border: 0;
		outline: 0;
		font: inherit;
		font-size: 0.75rem;
		color: var(--color-ink);
	}
	.graph-search:focus-within {
		outline: 2px solid var(--color-primary);
	}
	.graph-controls {
		position: absolute;
		z-index: 3;
		right: 0.7rem;
		top: 0.7rem;
		display: flex;
		align-items: center;
		gap: 0.3rem;
	}
	.icon-button {
		width: 30px;
		height: 30px;
		min-height: 30px;
	}
	.graph-controls .button {
		font-size: 0.7rem;
	}
	.graph-label {
		filter: saturate(var(--node-saturation, 1));
		position: absolute;
		left: 0;
		top: 0;
		transform-origin: 0 0;
		z-index: 1;
		width: 142px;
		height: 60px;
		display: flex;
		flex-direction: column;
		justify-content: space-between;
		padding: 0.25rem 0.45rem;
		border-radius: 0.6rem;
		background: color-mix(in srgb, var(--node-color) 5%, var(--color-surface));
		border: 2px solid color-mix(in srgb, var(--node-color) 85%, var(--color-border));
		box-shadow: var(--shadow-panel);
		cursor: grab;
		user-select: none;
	}
	.graph-label.master {
		width: 205px;
		height: 80px;
		padding: 0.5rem;
		border-color: var(--node-color);
		border-width: 2px;
		z-index: 2;
	}
	.master-title :global(strong) {
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
	.node-title,
	.master-title {
		all: unset;
		min-height: 0;
		overflow: hidden;
		display: flex;
		align-items: center;
		gap: 0.4rem;
		width: 100%;
		cursor: pointer;
		color: var(--color-ink);
		font-family: inherit;
	}
	.node-title {
		font-size: 0.69rem;
		line-height: 1.3;
	}
	.node-title > span {
		min-width: 0;
		overflow-wrap: anywhere;
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
	.node-title small {
		font-size: 0.55rem;
		opacity: 0.7;
		margin-left: auto;
	}
	.node-code {
		flex-shrink: 0;
		max-width: 55%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: var(--node-color);
		font-size: 0.75rem;
	}
	.node-title:focus-visible,
	.master-title:focus-visible {
		outline: 2px solid var(--color-primary);
		outline-offset: 3px;
	}
	.node-actions {
		flex-shrink: 0;
		display: flex;
		justify-content: flex-end;
		align-items: center;
		gap: 0.2rem;
		margin-top: 0.1rem;
	}
	.node-actions button {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 0.2rem;
		min-width: 21px;
		height: 17px;
		padding: 0 0.25rem;
		font-size: 0.65rem;
		font-family: inherit;
		border: 0;
		border-radius: 0.3rem;
		color: var(--node-color);
		background: color-mix(in srgb, var(--node-color) 10%, var(--color-surface));
		cursor: pointer;
	}
	.node-actions button:focus-visible {
		outline: 2px solid var(--node-color);
		outline-offset: -2px;
	}
	.branch-toggle {
		margin-right: auto;
	}
	.branch-toggle span {
		font-size: 0.55rem;
	}
	.node-actions .loader {
		width: 0.7rem;
		height: 0.7rem;
	}
	.graph-caption {
		position: absolute;
		z-index: 3;
		left: 0.8rem;
		right: 0.8rem;
		bottom: 0.6rem;
		display: flex;
		flex-wrap: wrap;
		justify-content: flex-end;
		gap: 0.7rem;
		align-items: center;
		font-size: 0.65rem;
		color: var(--color-muted);
		pointer-events: none;
	}
	.graph-caption span {
		margin-right: auto;
	}
	.graph-caption button {
		all: unset;
		pointer-events: auto;
		color: var(--color-primary);
		cursor: pointer;
	}
	.graph-caption button:focus-visible {
		outline: 2px solid var(--color-primary);
	}
	.search-results {
		max-width: 320px;
		max-height: 220px;
		overflow: auto;
		margin-top: 0.4rem;
		padding: 0.4rem;
		border: var(--border-thin);
		border-radius: 0.6rem;
		background: var(--color-surface);
	}
	.search-results button {
		display: block;
		width: 100%;
		text-align: left;
		padding: 0.4rem;
		border: 0;
		color: var(--color-ink);
		background: transparent;
		font-size: 0.75rem;
		cursor: pointer;
	}
	.text-mode {
		display: none;
	}
	.text-nodes {
		padding: 1rem;
		border: var(--border-thin);
		border-radius: 0.75rem;
		background: var(--color-surface);
	}
	.text-subject {
		display: flex;
		justify-content: space-between;
		gap: 0.5rem;
		margin: 0.6rem 0 0.4rem;
	}
	.competency-outline {
		list-style: none;
		padding: 0;
		margin: 0;
	}
	.competency-outline li {
		padding-inline-start: min(calc(var(--indent) * 1rem), 35%);
	}
	.text-node {
		display: flex;
		align-items: baseline;
		gap: 0.45rem;
		width: 100%;
		padding: 0.2rem 0.45rem;
		text-align: left;
		border: 0;
		border-left: 3px solid var(--parent-color);
		border-radius: 0.2rem;
		margin-bottom: 0.15rem;
		background: color-mix(in srgb, var(--outline-color) 5%, var(--color-surface));
		color: var(--color-ink);
		font: inherit;
		font-size: 0.8rem;
		line-height: 1.35;
		cursor: pointer;
	}
	.text-node strong {
		color: var(--outline-color);
		flex-shrink: 0;
	}
	.text-node span:not(.is-sr-only) {
		overflow-wrap: anywhere;
		min-width: 0;
	}
	.text-node:focus-visible {
		outline: 2px solid var(--color-primary);
		outline-offset: 1px;
	}
	.text-node small {
		color: var(--color-muted);
		margin-left: auto;
		flex-shrink: 0;
	}
	@media (max-width: 650px) {
		.graph-space {
			display: none;
			height: calc(100dvh - 220px);
			min-height: 480px;
		}
		.graph-controls {
			top: 3.1rem;
		}
		.graph-caption span {
			display: none;
		}
		.graph-label.master {
			width: 175px;
		}
		.graph-search {
			width: 160px;
		}
	}
</style>
