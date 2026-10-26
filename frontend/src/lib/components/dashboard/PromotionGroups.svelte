<script lang="ts">
	import { untrack } from 'svelte';
	import { beforeNavigate } from '$app/navigation';
	import { command, read } from '#lib/dashboard';
	import { groupError, groupLabel, moveStudent, partitionLabels } from '#lib/groups';
	import type { GroupDraft, Partition, PartitionKind, PromotionGroupsData } from '#lib/groups';
	import type { Promotion } from '#lib/types';
	import Icon from '../Icon.svelte';

	let {
		promotion,
		administrator,
		rosterRevision,
		ondirty,
		onchanged = () => {}
	}: {
		promotion: Promotion;
		administrator: boolean;
		rosterRevision: number;
		ondirty: (dirty: boolean) => void;
		onchanged?: () => void;
	} = $props();
	let data = $state<PromotionGroupsData>({ students: [], partitions: [] });
	let kind = $state<PartitionKind>('halves');
	let groups = $state<GroupDraft[]>([]);
	let targetSize = $state(3);
	let editing = $state(false);
	let loading = $state(true);
	let busy = $state(false);
	let stale = $state(false);
	let message = $state('');
	let success = $state('');
	let confirmation = $state<'generate' | 'delete' | 'reload' | null>(null);
	let selectedStudent = $state<number | null>(null);
	let listView = $state(false);
	let moving = $state<{
		number: number;
		pointer: number;
		startX: number;
		startY: number;
		x: number;
		y: number;
	} | null>(null);
	const saved = $derived(data.partitions.find((partition) => partition.kind === kind));
	const rosterIds = $derived(data.students.map((student) => student.id));
	const archivedIds = $derived(
		data.students.filter((student) => student.status === 'disabled').map((student) => student.id)
	);
	const archived = $derived(new Set(archivedIds));
	const nonArchivedCount = $derived(rosterIds.length - archivedIds.length);
	const names = $derived(
		new Map(
			data.students.map((student) => [student.id, `${student.first_name} ${student.last_name}`])
		)
	);
	const assigned = $derived(new Set(groups.flatMap((group) => group.student_ids)));
	const unassigned = $derived(data.students.filter((student) => !assigned.has(student.id)));
	const validation = $derived(groupError(kind, groups, rosterIds, targetSize, archivedIds));
	const editable = $derived(administrator && promotion.is_active);
	const boardWidth = $derived(Math.max(920, ...groups.map((group) => group.x + 300)));
	const boardHeight = $derived(
		Math.max(390, ...groups.map((group) => group.y + 140 + group.student_ids.length * 39))
	);

	function restore(): void {
		groups = structuredClone($state.snapshot(saved?.groups ?? []));
		targetSize = saved?.target_size ?? 3;
		selectedStudent = null;
	}
	function activeSize(group: GroupDraft): number {
		return group.student_ids.filter((id) => !archived.has(id)).length;
	}
	async function load(signal?: AbortSignal): Promise<void> {
		loading = true;
		message = '';
		try {
			const result = await read<PromotionGroupsData>(
				'promotionGroups',
				{ id: promotion.id },
				signal
			);
			if (signal?.aborted) return;
			data = result;
			stale = false;
			restore();
		} catch (cause) {
			if (!signal?.aborted) message = (cause as Error).message;
		} finally {
			if (!signal?.aborted) loading = false;
		}
	}
	$effect(() => {
		void rosterRevision;
		const controller = new AbortController();
		untrack(() => {
			if (editing) {
				stale = true;
				message =
					'Les membres de la promotion ont changé. Rechargez les groupes avant de les enregistrer.';
			} else void load(controller.signal);
		});
		return () => controller.abort();
	});
	$effect(() => {
		ondirty(editing);
	});
	beforeNavigate((navigation) => {
		if (editing && !window.confirm('Quitter sans enregistrer les groupes ?')) navigation.cancel();
	});
	function beforeUnload(event: BeforeUnloadEvent): void {
		if (editing) {
			event.preventDefault();
			event.returnValue = '';
		}
	}
	function choose(value: PartitionKind): void {
		kind = value;
		message = '';
		success = '';
		confirmation = null;
		restore();
	}
	function edit(): void {
		restore();
		editing = true;
		success = '';
	}
	function cancel(): void {
		editing = false;
		confirmation = null;
		message = '';
		restore();
		if (stale) void load();
	}
	function payload(): {
		expected_revision: string | null;
		roster_ids: number[];
		archived_ids: number[];
		target_size: number;
	} {
		return {
			expected_revision: saved?.revision ?? null,
			roster_ids: rosterIds,
			archived_ids: archivedIds,
			target_size: targetSize
		};
	}
	async function generate(): Promise<void> {
		busy = true;
		message = '';
		success = '';
		try {
			groups = await command<GroupDraft[]>('previewGroups', {
				id: promotion.id,
				kind,
				data: payload()
			});
			editing = true;
			selectedStudent = null;
			confirmation = null;
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
	async function save(): Promise<void> {
		busy = true;
		message = '';
		try {
			const result = await command<Partition>('saveGroups', {
				id: promotion.id,
				kind,
				data: { ...payload(), groups }
			});
			data.partitions = [...data.partitions.filter((partition) => partition.kind !== kind), result];
			editing = false;
			selectedStudent = null;
			success = 'Répartition enregistrée.';
			onchanged();
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
	async function remove(): Promise<void> {
		busy = true;
		message = '';
		try {
			await command('deleteGroups', {
				id: promotion.id,
				kind,
				data: { expected_revision: saved?.revision ?? null }
			});
			data.partitions = data.partitions.filter((partition) => partition.kind !== kind);
			editing = false;
			confirmation = null;
			restore();
			success = 'Répartition supprimée.';
			onchanged();
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
	function transfer(number: number): void {
		if (!editing || busy || selectedStudent === null) return;
		const name = names.get(selectedStudent);
		groups = moveStudent(groups, selectedStudent, number);
		selectedStudent = null;
		success = `${name} a été déplacé vers ${groupLabel(kind, number)}. Modification non enregistrée.`;
	}
	function drop(event: DragEvent, number: number): void {
		event.preventDefault();
		if (!editing || busy) return;
		const id = Number(event.dataTransfer?.getData('application/x-sophikron-student'));
		if (!names.has(id)) return;
		selectedStudent = id;
		transfer(number);
	}
	function startMoving(event: PointerEvent, group: GroupDraft): void {
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
		const { number, x, y, startX, startY } = moving;
		groups = groups.map((group) =>
			group.number === number
				? {
						...group,
						x: Math.round(Math.max(0, Math.min(1000000, x + event.clientX - startX))),
						y: Math.round(Math.max(0, Math.min(1000000, y + event.clientY - startY)))
					}
				: group
		);
	}
	function moveWithKeyboard(event: KeyboardEvent, group: GroupDraft): void {
		const offsets: Record<string, [number, number]> = {
			ArrowLeft: [-20, 0],
			ArrowRight: [20, 0],
			ArrowUp: [0, -20],
			ArrowDown: [0, 20]
		};
		const offset = offsets[event.key];
		if (!offset || listView || busy) return;
		event.preventDefault();
		groups = groups.map((item) =>
			item.number === group.number
				? {
						...item,
						x: Math.max(0, Math.min(1000000, item.x + offset[0])),
						y: Math.max(0, Math.min(1000000, item.y + offset[1]))
					}
				: item
		);
	}
	function arrange(): void {
		groups = groups.map((group, index) => ({
			...group,
			x: (index % 3) * 300 + 20,
			y: Math.floor(index / 3) * 350 + 20
		}));
	}
	function addGroup(): void {
		const used = new Set(groups.map((group) => group.number));
		let number = 1;
		while (used.has(number)) number += 1;
		groups = [
			...groups,
			{
				number,
				x: ((number - 1) % 3) * 300 + 20,
				y: Math.floor((number - 1) / 3) * 350 + 20,
				student_ids: []
			}
		].sort((left, right) => left.number - right.number);
	}
	function removeEmpty(number: number): void {
		groups = groups.filter((group) => group.number !== number);
	}
</script>

<svelte:window onbeforeunload={beforeUnload} />
<section
	class="workspace-panel groups-panel"
	aria-label="Répartitions des élèves"
	style={`--promotion-color: ${promotion.color}`}
>
	<div class="panel-heading">
		<div>
			<p class="eyebrow">Organisation de la promotion</p>
			<h3 class="title is-4 mb-2">Les groupes</h3>
			<p class="muted text-small">
				Trois répartitions indépendantes. Déplacez les bulles pour explorer les groupes.
			</p>
			<p class="muted text-small">
				Les élèves grisés sont archivés : leurs groupes sont conservés, mais ils sont exclus des
				effectifs et de l’équilibrage.
			</p>
		</div>
		<button
			class="button is-light"
			disabled={busy || loading}
			onclick={() => (editing ? (confirmation = 'reload') : void load())}
			><Icon name="restore" />Actualiser</button
		>
	</div>
	<div class="tabs is-toggle is-toggle-rounded">
		<ul>
			{#each Object.entries(partitionLabels) as [value, label] (value)}
				<li class:is-active={kind === value}>
					<button
						class="partition-tab"
						aria-pressed={kind === value}
						disabled={editing || busy || loading}
						onclick={() => choose(value as PartitionKind)}>{label}</button
					>
				</li>
			{/each}
		</ul>
	</div>
	{#if editing}<div class="group-save" role="group" aria-label="Actions d’édition des groupes">
			<span class="muted text-small">Modifications non enregistrées</span>
			<div class="buttons mb-0">
				<button
					class="button is-primary is-small"
					disabled={busy || !!validation || stale}
					class:is-loading={busy}
					onclick={save}><Icon name="save" />Enregistrer</button
				>
				<button class="button is-light is-small" disabled={busy} onclick={cancel}>Annuler</button>
			</div>
			{#if validation}<p class="save-validation text-small" role="status">{validation}</p>{/if}
		</div>{/if}
	{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
	{#if success}<p class="notification is-success is-light" role="status">{success}</p>{/if}
	{#if loading}<p class="loading-state" role="status">Chargement des groupes…</p>
	{:else}
		{#if editable && !editing}
			<div class="group-toolbar">
				{#if kind === 'kholles'}<div class="field mb-0">
						<label class="label text-small" for={`kholle-size-${promotion.id}`}
							>Taille cible à la génération</label
						>
						<div class="select">
							<select
								id={`kholle-size-${promotion.id}`}
								bind:value={targetSize}
								disabled={busy || editing}
							>
								{#each [2, 3, 4, 5] as size (size)}<option value={size}>{size} élèves</option
									>{/each}
							</select>
						</div>
					</div>{/if}
				<div class="buttons mb-0">
					<button
						class="button is-primary"
						disabled={busy || editing || !data.students.length}
						onclick={() => (saved ? (confirmation = 'generate') : void generate())}
						><Icon name="plus" />{saved ? 'Régénérer' : 'Générer'}</button
					>
					{#if saved && !editing}<button class="button is-light" disabled={busy} onclick={edit}
							><Icon name="edit" />Modifier les groupes</button
						>
						<button
							class="button is-danger is-light"
							disabled={busy}
							onclick={() => (confirmation = 'delete')}
							><Icon name="remove" />Supprimer la répartition</button
						>{/if}
				</div>
			</div>
		{/if}
		{#if confirmation}<div class="confirmation-panel mt-4" role="alert">
				<p class="has-text-weight-semibold">
					{confirmation === 'delete'
						? 'Supprimer toute cette répartition ?'
						: confirmation === 'reload'
							? 'Abandonner les modifications et recharger ?'
							: 'Préparer une nouvelle répartition aléatoire ?'}
				</p>
				<p class="muted mt-2">
					{confirmation === 'delete'
						? 'Les groupes de cette répartition seront supprimés. Les élèves restent dans la promotion et les autres répartitions sont conservées.'
						: confirmation === 'reload'
							? 'Les modifications non enregistrées seront perdues.'
							: 'La répartition actuelle ne sera remplacée qu’après enregistrement de la nouvelle.'}
				</p>
				<div class="buttons mt-3">
					<button
						class="button is-primary"
						disabled={busy}
						class:is-loading={busy}
						onclick={() =>
							confirmation === 'delete'
								? void remove()
								: confirmation === 'generate'
									? void generate()
									: (cancel(), void load())}>Confirmer</button
					>
					<button class="button is-light" disabled={busy} onclick={() => (confirmation = null)}
						>Annuler</button
					>
				</div>
			</div>{/if}
		{#if editing}<div class="notification is-info is-light mt-4">
				<p>
					<strong>Mode édition · modifications non enregistrées.</strong> Glissez un nom vers un autre
					groupe, ou cliquez sur un élève puis sur « Déplacer ici ».
				</p>
				<p class="mt-2">
					{kind === 'kholles'
						? `À la sauvegarde, chaque groupe comptant des élèves non archivés doit en contenir ${targetSize}.${nonArchivedCount % targetSize ? ` Un seul groupe doit contenir le reste (${nonArchivedCount % targetSize} élève(s)).` : ' Aucun groupe actif réduit n’est autorisé.'} Les groupes composés uniquement d’archivés sont conservés hors calcul.`
						: 'À la sauvegarde, les effectifs non archivés doivent avoir au maximum un élève d’écart.'}
					Chaque élève doit être affecté une fois.
				</p>
			</div>{/if}
		{#if groups.length}
			<div class="group-toolbar mt-4">
				<p class="muted text-small">
					{editing
						? 'La disposition des bulles sera enregistrée avec les groupes.'
						: 'Les déplacements en consultation restent temporaires.'}
				</p>
				<div class="buttons mb-0">
					<button
						class="button is-small is-light"
						disabled={busy}
						onclick={() => (listView = !listView)}>{listView ? 'Vue bulles' : 'Vue liste'}</button
					>
					<button class="button is-small is-light" disabled={busy} onclick={arrange}
						>Ranger les bulles</button
					>
					{#if editing && kind === 'kholles'}<button
							class="button is-small is-light"
							disabled={busy || groups.length >= 1000}
							onclick={addGroup}><Icon name="plus" />Ajouter un groupe</button
						>{/if}
				</div>
			</div>
			{#if unassigned.length}<div class="notification is-warning is-light mt-4">
					<p class="has-text-weight-semibold">Élèves à affecter ({unassigned.length})</p>
					<p class="text-small mb-2">
						La promotion a évolué depuis l’enregistrement de cette répartition.
					</p>
					<div class="student-chips">
						{#each unassigned as student (student.id)}
							<button
								class="student-chip"
								class:chosen={selectedStudent === student.id}
								class:archived-account={archived.has(student.id)}
								title={archived.has(student.id) ? 'Compte archivé, exclu des effectifs' : undefined}
								disabled={!editing || busy}
								aria-pressed={selectedStudent === student.id}
								onclick={() =>
									(selectedStudent = selectedStudent === student.id ? null : student.id)}
								>{names.get(student.id)}</button
							>
						{/each}
					</div>
				</div>{/if}
			<!-- svelte-ignore a11y_no_noninteractive_tabindex (Scrollable map must be keyboard focusable.) -->
			<div
				class="group-viewport mt-4"
				class:list-view={listView}
				tabindex="0"
				role="region"
				aria-label="Carte des groupes, défilement horizontal et vertical"
			>
				<div
					class="group-board"
					style={listView ? '' : `width:${boardWidth}px;min-height:${boardHeight}px`}
				>
					{#each groups as group (group.number)}
						<section
							class="group-bubble"
							class:over-limit={editing && kind === 'kholles' && activeSize(group) > targetSize}
							style={listView ? '' : `left:${group.x}px;top:${group.y}px`}
							aria-label={groupLabel(kind, group.number)}
						>
							<button
								class="bubble-handle"
								disabled={busy || listView}
								onpointerdown={(event) => startMoving(event, group)}
								onpointermove={moveBubble}
								onpointerup={() => (moving = null)}
								onpointercancel={() => (moving = null)}
								onkeydown={(event) => moveWithKeyboard(event, group)}
								aria-label={`Déplacer la bulle ${groupLabel(kind, group.number)} ; utilisez les flèches du clavier`}
							>
								<Icon name="promotions" /><strong>{groupLabel(kind, group.number)}</strong><span
									class="tag is-rounded"
									title="Élèves non archivés">{activeSize(group)}</span
								>
								{#if group.student_ids.length > activeSize(group)}<span class="muted text-small"
										>+{group.student_ids.length - activeSize(group)} archivé{group.student_ids
											.length -
											activeSize(group) ===
										1
											? ''
											: 's'}</span
									>{/if}
							</button>
							<div
								class="bubble-members"
								role="group"
								aria-label={`Élèves de ${groupLabel(kind, group.number)}`}
								ondragover={(event) => {
									if (editing) event.preventDefault();
								}}
								ondrop={(event) => drop(event, group.number)}
							>
								{#each group.student_ids as id (id)}<button
										class="student-chip"
										class:chosen={selectedStudent === id}
										class:archived-account={archived.has(id)}
										title={archived.has(id) ? 'Compte archivé, exclu des effectifs' : undefined}
										disabled={!editing || busy}
										draggable={editing && !busy}
										aria-pressed={selectedStudent === id}
										ondragstart={(event) => {
											selectedStudent = id;
											event.dataTransfer?.setData('application/x-sophikron-student', String(id));
											if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move';
										}}
										ondragend={() => (selectedStudent = null)}
										onclick={() => (selectedStudent = selectedStudent === id ? null : id)}
										>{names.get(id)}</button
									>{/each}
								{#if group.student_ids.length === 0}<p class="muted text-small">Groupe vide</p>{/if}
								{#if editing}<button
										class="button is-small is-light transfer-button"
										disabled={busy || selectedStudent === null}
										onclick={() => transfer(group.number)}>Déplacer ici</button
									>{/if}
							</div>
							{#if editing && kind === 'kholles' && group.student_ids.length === 0}<button
									class="button is-small is-text"
									disabled={busy}
									onclick={() => removeEmpty(group.number)}>Retirer ce groupe vide</button
								>{/if}
						</section>
					{/each}
				</div>
			</div>
		{:else}<div class="empty-state mt-4">
				<Icon name="promotions" size={30} />
				<p>
					{data.students.length
						? 'Aucune répartition créée pour cette catégorie.'
						: 'Aucun élève dans cette promotion.'}
				</p>
			</div>{/if}
	{/if}
</section>

<style>
	.groups-panel {
		margin-top: 1.5rem;
	}
	.partition-tab {
		border: 0;
		background: transparent;
		color: inherit;
		padding: 0.7rem 1rem;
		font: inherit;
		cursor: pointer;
	}
	.tabs li.is-active {
		background: var(--color-primary);
		color: var(--color-on-primary);
		border-radius: 2rem;
	}
	.partition-tab:disabled {
		cursor: default;
		opacity: 0.7;
	}
	.group-toolbar {
		display: flex;
		flex-wrap: wrap;
		align-items: end;
		justify-content: space-between;
		gap: 1rem;
	}
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
	.student-chips {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
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
	.group-save {
		position: sticky;
		top: 0.75rem;
		z-index: 5;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 0.5rem 1rem;
		margin-bottom: 1rem;
		padding: 0.7rem 0.9rem;
		background: var(--color-surface);
		border: var(--border-thin);
		border-radius: var(--radius-small);
		box-shadow: var(--shadow-panel);
	}
	.group-save .buttons {
		flex-wrap: nowrap;
	}
	.save-validation {
		flex-basis: 100%;
		color: var(--color-warning);
	}
	@media (max-width: 600px) {
		.partition-tab {
			font-size: 0.8rem;
			padding: 0.65rem 0.6rem;
		}
		.list-view .group-board {
			grid-template-columns: 1fr;
		}
	}
</style>
