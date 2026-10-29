<script module lang="ts">
	export interface GroupMapNode {
		number: number;
		label: string;
		x: number;
		y: number;
		student_ids: number[];
		overLimit?: boolean;
	}
	export interface GroupMapStudent {
		id: number;
		name: string;
		archived: boolean;
	}
</script>

<script lang="ts">
	import type { Snippet } from 'svelte';
	import Icon from '../Icon.svelte';
	let {
		groups,
		students,
		editing,
		busy = false,
		listView = false,
		selectedStudent = $bindable(null),
		editableGroups,
		copyMembers = false,
		ontransfer,
		oncreate,
		onmove,
		actions
	}: {
		groups: GroupMapNode[];
		students: GroupMapStudent[];
		editing: boolean;
		busy?: boolean;
		listView?: boolean;
		selectedStudent?: number | null;
		editableGroups?: number[];
		copyMembers?: boolean;
		ontransfer: (student: number, source: number | null, target: number) => void;
		oncreate?: (students: number[], x: number, y: number) => void;
		onmove: (number: number, x: number, y: number) => void;
		actions?: Snippet<[GroupMapNode]>;
	} = $props();
	let selectedGroup = $state<number | null>(null);
	let moving = $state<{
		number: number;
		pointer: number;
		startX: number;
		startY: number;
		x: number;
		y: number;
	} | null>(null);
	const names = $derived(new Map(students.map((student) => [student.id, student])));
	const boardWidth = $derived(Math.max(920, ...groups.map((group) => group.x + 300)));
	const boardHeight = $derived(
		Math.max(390, ...groups.map((group) => group.y + 180 + group.student_ids.length * 39))
	);
	function accepts(number: number): boolean {
		return editing && !busy && (!editableGroups || editableGroups.includes(number));
	}
	function transfer(number: number): void {
		if (selectedStudent === null || !accepts(number)) return;
		ontransfer(selectedStudent, selectedGroup, number);
		selectedStudent = null;
		selectedGroup = null;
	}
	function drop(event: DragEvent, number: number): void {
		event.preventDefault();
		event.stopPropagation();
		if (!accepts(number)) return;
		const id = Number(event.dataTransfer?.getData('application/x-sophikron-student'));
		if (!names.has(id)) return;
		selectedStudent = id;
		const source = event.dataTransfer?.getData('application/x-sophikron-group');
		selectedGroup = source ? Number(source) : null;
		transfer(number);
	}
	function createFromDrop(event: DragEvent, group?: GroupMapNode, pupil?: number): void {
		if (!oncreate || !editing || busy) return;
		if (!group && (event.target as HTMLElement).closest('.group-bubble')) return;
		event.preventDefault();
		event.stopPropagation();
		const id = Number(event.dataTransfer?.getData('application/x-sophikron-student'));
		if (!names.has(id) || id === pupil) return;
		const board = (event.currentTarget as HTMLElement).getBoundingClientRect();
		oncreate(
			pupil === undefined ? [id] : [id, pupil],
			group ? group.x + 30 : event.clientX - board.left,
			group ? boardHeight + 20 : event.clientY - board.top
		);
		selectedStudent = null;
		selectedGroup = null;
	}
	function startMoving(event: PointerEvent, group: GroupMapNode): void {
		if (listView || busy || event.button !== 0) return;
		(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
		moving = {
			number: group.number,
			pointer: event.pointerId,
			startX: event.clientX,
			startY: event.clientY,
			x: group.x,
			y: group.y
		};
	}
	function moveBubble(event: PointerEvent): void {
		if (!moving || event.pointerId !== moving.pointer) return;
		onmove(
			moving.number,
			Math.round(Math.max(0, Math.min(1000000, moving.x + event.clientX - moving.startX))),
			Math.round(Math.max(0, Math.min(1000000, moving.y + event.clientY - moving.startY)))
		);
	}
	function moveWithKeyboard(event: KeyboardEvent, group: GroupMapNode): void {
		const offsets: Record<string, [number, number]> = {
			ArrowLeft: [-20, 0],
			ArrowRight: [20, 0],
			ArrowUp: [0, -20],
			ArrowDown: [0, 20]
		};
		const offset = offsets[event.key];
		if (!offset || listView || busy) return;
		event.preventDefault();
		onmove(
			group.number,
			Math.max(0, Math.min(1000000, group.x + offset[0])),
			Math.max(0, Math.min(1000000, group.y + offset[1]))
		);
	}
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex (Scrollable group map needs keyboard focus.) -->
<div
	class="group-viewport mt-4"
	class:list-view={listView}
	tabindex="0"
	role="region"
	aria-label="Carte des groupes, défilement horizontal et vertical"
>
	<div
		class="group-board"
		role="group"
		aria-label="Disposition des groupes"
		ondragover={(event) => {
			if (oncreate && editing && !busy) event.preventDefault();
		}}
		ondrop={(event) => createFromDrop(event)}
		style={listView ? '' : `width:${boardWidth}px;min-height:${boardHeight}px`}
	>
		{#each groups as group (group.number)}
			{@const activeSize = group.student_ids.filter((id) => !names.get(id)?.archived).length}
			<section
				class="group-bubble"
				class:over-limit={group.overLimit}
				style={listView ? '' : `left:${group.x}px;top:${group.y}px`}
				aria-label={group.label}
			>
				<button
					class="bubble-handle"
					disabled={busy || listView}
					onpointerdown={(event) => startMoving(event, group)}
					onpointermove={moveBubble}
					onpointerup={() => (moving = null)}
					onpointercancel={() => (moving = null)}
					onkeydown={(event) => moveWithKeyboard(event, group)}
					aria-label={`Déplacer la bulle ${group.label} ; utilisez les flèches du clavier`}
				>
					<Icon name="promotions" /><strong>{group.label}</strong><span
						class="tag is-rounded"
						title="Élèves non archivés">{activeSize}</span
					>
					{#if group.student_ids.length > activeSize}<span class="muted text-small"
							>+{group.student_ids.length - activeSize} archivé(s)</span
						>{/if}
				</button>
				<div
					class="bubble-members"
					role="group"
					aria-label={`Élèves de ${group.label}`}
					ondragover={(event) => {
						if (accepts(group.number)) event.preventDefault();
					}}
					ondrop={(event) => drop(event, group.number)}
				>
					{#each group.student_ids as id (id)}<button
							class="student-chip"
							class:chosen={selectedStudent === id &&
								(selectedGroup === group.number || !copyMembers)}
							class:archived-account={names.get(id)?.archived}
							aria-label={`${names.get(id)?.name ?? 'Élève'}${names.get(id)?.archived ? ' · Archivé' : ''}`}
							title={names.get(id)?.archived ? 'Compte archivé, exclu des effectifs' : undefined}
							disabled={!editing || busy}
							draggable={editing && !busy}
							ondragover={(event) => {
								if (oncreate && editing && !busy) {
									event.preventDefault();
									event.stopPropagation();
								}
							}}
							ondrop={(event) => {
								if (oncreate) createFromDrop(event, group, id);
							}}
							aria-pressed={selectedStudent === id &&
								(selectedGroup === group.number || !copyMembers)}
							ondragstart={(event) => {
								selectedStudent = id;
								selectedGroup = group.number;
								event.dataTransfer?.setData('application/x-sophikron-student', String(id));
								event.dataTransfer?.setData('application/x-sophikron-group', String(group.number));
								if (event.dataTransfer)
									event.dataTransfer.effectAllowed = copyMembers ? 'copyMove' : 'move';
							}}
							ondragend={() => {
								selectedStudent = null;
								selectedGroup = null;
							}}
							onclick={() => {
								selectedStudent =
									selectedStudent === id && selectedGroup === group.number ? null : id;
								selectedGroup = group.number;
							}}
							><span class="student-name">{names.get(id)?.name ?? 'Élève'}</span
							>{#if names.get(id)?.archived}<span class="text-small"> · Archivé</span>{/if}</button
						>{/each}
					{#if !group.student_ids.length}<p class="muted text-small">Groupe vide</p>{/if}
					{#if accepts(group.number)}<button
							class="button is-small is-light transfer-button"
							disabled={selectedStudent === null ||
								(copyMembers && group.number === 0 && (!selectedGroup || selectedGroup === 0))}
							onclick={() => transfer(group.number)}
							>{copyMembers
								? group.number === 0
									? 'Retirer du groupe'
									: 'Ajouter ici'
								: 'Déplacer ici'}</button
						>{/if}
				</div>
				{@render actions?.(group)}
			</section>
		{/each}
	</div>
</div>

<style>
	.group-viewport {
		overflow: auto;
		max-height: 75vh;
		border: 1px solid var(--color-border);
		border-radius: 1.4rem;
		background-color: var(--color-surface);
		background-image: radial-gradient(
			color-mix(in srgb, var(--promotion-color) 22%, transparent) 1px,
			transparent 1px
		);
		background-size: 20px 20px;
	}
	.group-board {
		position: relative;
	}
	.group-bubble {
		position: absolute;
		width: 264px;
		border: 1px solid color-mix(in srgb, var(--promotion-color) 40%, var(--color-border));
		border-radius: 1.6rem;
		padding: 0.85rem;
		background: var(--color-surface);
		box-shadow: 0 8px 24px #0000000a;
	}
	.bubble-handle {
		width: 100%;
		display: flex;
		gap: 0.6rem;
		align-items: center;
		border: 0;
		background: transparent;
		color: var(--color-ink);
		padding: 0.3rem 0.2rem 0.8rem;
		cursor: grab;
		touch-action: none;
		font: inherit;
	}
	.bubble-handle .tag {
		margin-left: auto;
	}
	.bubble-handle strong {
		min-width: 0;
		overflow-wrap: anywhere;
		text-align: left;
		flex: 1;
	}
	.bubble-handle:active {
		cursor: grabbing;
	}
	.bubble-handle:disabled {
		opacity: 1;
		cursor: default;
	}
	.bubble-members {
		display: grid;
		gap: 0.4rem;
		min-height: 60px;
	}

	.student-chip {
		border: 1px solid var(--color-border);
		border-radius: 1rem;
		background: var(--color-subtle);
		color: var(--color-ink);
		font: inherit;
		font-size: 0.85rem;
		text-align: left;
		padding: 0.4rem 0.7rem;
		overflow-wrap: anywhere;
		cursor: grab;
	}
	.student-chip:disabled {
		opacity: 1;
		cursor: default;
	}
	.student-chip.chosen {
		outline: 2px solid var(--promotion-color);
		background: color-mix(in srgb, var(--promotion-color) 12%, var(--color-surface));
	}
	.student-chip.archived-account {
		color: var(--color-muted);
		border-style: dashed;
		background: var(--color-subtle);
	}
	.archived-account .student-name {
		text-decoration: line-through;
	}
	.over-limit {
		border: 2px solid var(--color-danger);
	}
	.transfer-button {
		margin-top: 0.4rem;
		border: 1px dashed var(--promotion-color);
	}
	.list-view {
		max-height: none;
	}
	.list-view .group-board {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
		gap: 1rem;
		padding: 1rem;
	}
	.list-view .group-bubble {
		position: relative;
		width: auto;
	}

	@media (max-width: 600px) {
		.list-view .group-board {
			grid-template-columns: 1fr;
		}
	}
</style>
