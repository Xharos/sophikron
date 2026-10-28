<script lang="ts">
	import { untrack } from 'svelte';
	import { beforeNavigate } from '$app/navigation';
	import { command, read } from '#lib/dashboard';
	import { groupError, groupLabel, moveStudent, partitionLabels } from '#lib/groups';
	import type { GroupDraft, Partition, PartitionKind, PromotionGroupsData } from '#lib/groups';
	import type { Promotion } from '#lib/types';
	import Icon from '../Icon.svelte';
	import CustomPromotionGroups from './CustomPromotionGroups.svelte';
	import GroupMap from './GroupMap.svelte';

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
	let custom = $state(false);
	let customDirty = $state(false);
	let customRefresh = $state(0);
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
		ondirty(editing || customDirty);
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
		custom = false;
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
				Répartitions et groupes personnalisés. Déplacez les bulles pour explorer les groupes.
			</p>
			<p class="muted text-small">
				Les élèves grisés sont archivés : leurs groupes sont conservés, mais ils sont exclus des
				effectifs et de l’équilibrage.
			</p>
		</div>
		<button
			class="button is-light"
			onclick={() => {
				if (custom) customRefresh += 1;
				else if (editing) confirmation = 'reload';
				else void load();
			}}
			disabled={busy || loading || customDirty}><Icon name="restore" />Actualiser</button
		>
	</div>
	<div class="tabs is-toggle is-toggle-rounded">
		<ul>
			{#each Object.entries(partitionLabels) as [value, label] (value)}
				<li class:is-active={!custom && kind === value}>
					<button
						class="partition-tab"
						aria-pressed={!custom && kind === value}
						disabled={editing || customDirty || busy || loading}
						onclick={() => choose(value as PartitionKind)}>{label}</button
					>
				</li>
			{/each}
			<li class:is-active={custom}>
				<button
					class="partition-tab"
					aria-pressed={custom}
					disabled={editing || customDirty || busy || loading}
					onclick={() => {
						custom = true;
						message = '';
						success = '';
					}}>Groupes personnalisés</button
				>
			</li>
		</ul>
	</div>
	{#if custom}<CustomPromotionGroups
			promotionId={promotion.id}
			students={data.students}
			{editable}
			rosterRevision={rosterRevision + customRefresh}
			ondirty={(value) => (customDirty = value)}
			{onchanged}
		/>{:else}
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
									title={archived.has(student.id)
										? 'Compte archivé, exclu des effectifs'
										: undefined}
									disabled={!editing || busy}
									aria-pressed={selectedStudent === student.id}
									onclick={() =>
										(selectedStudent = selectedStudent === student.id ? null : student.id)}
									>{names.get(student.id)}</button
								>
							{/each}
						</div>
					</div>{/if}
				<GroupMap
					groups={groups.map((group) => ({
						...group,
						label: groupLabel(kind, group.number),
						overLimit: editing && kind === 'kholles' && activeSize(group) > targetSize
					}))}
					students={data.students.map((student) => ({
						id: student.id,
						name: names.get(student.id) ?? '',
						archived: archived.has(student.id)
					}))}
					{editing}
					{busy}
					{listView}
					bind:selectedStudent
					ontransfer={(id, _source, target) => {
						selectedStudent = id;
						transfer(target);
					}}
					onmove={(number, x, y) =>
						(groups = groups.map((group) =>
							group.number === number ? { ...group, x, y } : group
						))}
				>
					{#snippet actions(
						group
					)}{#if editing && kind === 'kholles' && !group.student_ids.length}<button
								class="button is-small is-text"
								disabled={busy}
								onclick={() => removeEmpty(group.number)}>Retirer ce groupe vide</button
							>{/if}{/snippet}
				</GroupMap>
			{:else}<div class="empty-state mt-4">
					<Icon name="promotions" size={30} />
					<p>
						{data.students.length
							? 'Aucune répartition créée pour cette catégorie.'
							: 'Aucun élève dans cette promotion.'}
					</p>
				</div>{/if}
		{/if}
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
	.student-chips {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
	}
	.student-chip {
		border: 1px solid var(--color-border);
		border-radius: 1rem;
		padding: 0.4rem 0.7rem;
		background: var(--color-subtle);
		color: var(--color-ink);
		font: inherit;
		font-size: 0.85rem;
		cursor: pointer;
	}
	.student-chip.chosen {
		outline: 2px solid var(--promotion-color);
	}
	.student-chip.archived-account {
		color: var(--color-muted);
		border-style: dashed;
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
	}
</style>
