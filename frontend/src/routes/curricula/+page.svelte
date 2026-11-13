<script lang="ts">
	import { untrack } from 'svelte';
	import CompetencyTransfer from '#lib/components/curricula/CompetencyTransfer.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import CompetencyCanvas from '#lib/components/curricula/CompetencyCanvas.svelte';
	import CompetencyEditor from '#lib/components/curricula/CompetencyEditor.svelte';
	import CurriculumEditor from '#lib/components/curricula/CurriculumEditor.svelte';
	import {
		curriculumRequest,
		type CompetencyGraph,
		type CurriculumCatalog,
		type Competency,
		type Curriculum
	} from '#lib/curricula';
	import type { PageProps } from './$types';
	let { data }: PageProps = $props();
	let catalog = $state<CurriculumCatalog>(untrack(() => data.catalog));
	let curriculumId = $state(
		untrack(() => catalog.curricula.find((c) => c.is_active)?.id ?? catalog.curricula[0]?.id ?? 0)
	);
	let graphs = $state<Record<number, CompetencyGraph>>({});
	let pending = $state<number[]>([]),
		message = $state('');
	let editor = $state<{ subjectId: number; node?: Competency; parentId?: number } | null>(null);
	let settings = $state<Curriculum | 'new' | null>(null);
	let transferMode = $state<'import' | 'export' | null>(null);
	let generation = 0;
	let undoVersion = $state<number | null>(null),
		undoBusy = $state(false);
	function acceptEdit(updated: CompetencyGraph): void {
		graphs = { ...graphs, [updated.subject_id]: updated };
		undoVersion = updated.can_undo ? updated.version : null;
	}
	async function undo(): Promise<void> {
		if (undoVersion === null || undoBusy) return;
		undoBusy = true;
		try {
			acceptEdit(
				await curriculumRequest<CompetencyGraph>('undo', {
					curriculum_id: curriculumId,
					data: { expected_version: undoVersion }
				})
			);
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			undoBusy = false;
		}
	}
	function shortcut(event: KeyboardEvent): void {
		if (
			!(event.ctrlKey || event.metaKey) ||
			event.key.toLowerCase() !== 'z' ||
			event.shiftKey ||
			document.querySelector('dialog[open]')
		)
			return;
		if (
			event.target instanceof Element &&
			event.target.closest('input,textarea,select,[contenteditable]')
		)
			return;
		if (undoVersion !== null) {
			event.preventDefault();
			void undo();
		}
	}
	const loads: Partial<Record<string, Promise<void>>> = {};
	const curriculum = $derived(catalog.curricula.find((c) => c.id === curriculumId));
	const subjects = $derived(catalog.subjects.filter((s) => curriculum?.subject_ids.includes(s.id)));
	const editingGraph = $derived(editor ? graphs[editor.subjectId] : undefined);
	const editable = $derived(
		!!curriculum?.is_active &&
			!!subjects.find((s) => s.id === editor?.subjectId && s.is_active && s.can_edit)
	);
	$effect(() => {
		void curriculumId;
		generation++;
		undoVersion = null;
		graphs = {};
		pending = [];
		editor = null;
		message = '';
	});
	async function loadSubject(subjectId: number): Promise<void> {
		if (graphs[subjectId]) return;
		const key = `${generation}:${subjectId}`;
		if (loads[key]) return loads[key];
		const selected = curriculumId,
			requestGeneration = generation;
		pending = [...pending, subjectId];
		const operation = (async () => {
			try {
				const graph = await curriculumRequest<CompetencyGraph>('graph', {
					curriculum_id: selected,
					subject_id: subjectId
				});
				if (requestGeneration === generation) graphs = { ...graphs, [subjectId]: graph };
			} catch (cause) {
				if (requestGeneration === generation) message = (cause as Error).message;
			} finally {
				if (requestGeneration === generation) pending = pending.filter((id) => id !== subjectId);
				delete loads[key];
			}
		})();
		loads[key] = operation;
		return operation;
	}
	$effect(() => {
		void curriculumId;
		const ids = subjects.map((subject) => subject.id);
		untrack(() => ids.forEach((id) => void loadSubject(id)));
	});
	async function add(subjectId: number, parentId?: number): Promise<void> {
		await loadSubject(subjectId);
		if (graphs[subjectId]) editor = { subjectId, parentId };
	}
	async function saved(result: Curriculum): Promise<void> {
		try {
			catalog = await curriculumRequest<CurriculumCatalog>('catalog');
			curriculumId = result.id;
		} catch (cause) {
			message = (cause as Error).message;
		}
	}
</script>

<svelte:window onkeydown={shortcut} />

<svelte:head
	><title>Référentiels — {data.establishmentName}</title><meta
		name="description"
		content="Explorez les matières et compétences des référentiels pédagogiques."
	/><meta name="robots" content="noindex, nofollow" /></svelte:head
>

<section class="curricula-page">
	<header class="curricula-heading">
		<div class="heading-title">
			<Icon name="book" size={21} />
			<h1>Référentiels</h1>
		</div>
		{#if catalog.curricula.length}<div class="select is-small">
				<select aria-label="Référentiel" bind:value={curriculumId}
					>{#each catalog.curricula as item (item.id)}<option value={item.id}
							>{item.title}{item.is_active ? '' : ' · Archivé'}</option
						>{/each}</select
				>
			</div>{/if}
		{#if curriculum?.source_url}
			<!-- eslint-disable svelte/no-navigation-without-resolve -->
			<a
				class="button is-light is-small"
				href={curriculum.source_url}
				target="_blank"
				rel="noopener noreferrer"><Icon name="book" size={13} />PDF officiel</a
			>
			<!-- eslint-enable svelte/no-navigation-without-resolve -->
		{/if}
		<div class="heading-actions">
			{#if curriculum}<button
					class="button is-light is-small"
					aria-label="Exporter les compétences"
					title="Exporter les compétences"
					onclick={() => (transferMode = 'export')}><Icon name="download" /></button
				>
				{#if curriculum.is_active && subjects.some((s) => s.can_edit && s.is_active)}<button
						class="button is-light is-small"
						aria-label="Importer des compétences"
						title="Importer des compétences"
						onclick={() => (transferMode = 'import')}><Icon name="upload" /></button
					>{/if}{/if}
			<button
				class="button is-light is-small"
				disabled={undoVersion === null || undoBusy}
				onclick={() => {
					void undo();
				}}
				aria-label="Annuler l’action (Ctrl+Z)"
				title="Annuler l’action (Ctrl+Z)"><Icon name="restore" /></button
			>
			{#if catalog.can_manage}{#if curriculum}<button
						class="button is-light is-small"
						onclick={() => (settings = curriculum ?? null)}
						aria-label="Modifier"
						title="Modifier le référentiel"><Icon name="edit" /></button
					>{/if}<button class="button is-primary is-small" onclick={() => (settings = 'new')}
					><Icon name="plus" />Nouveau référentiel</button
				>{/if}
		</div>
	</header>
	{#if curriculum?.description}<p class="curriculum-description muted">
			{curriculum.description}
		</p>{/if}
	{#if message}<div class="notification is-danger is-light" role="alert">
			{message}<button class="button is-light is-small ml-3" onclick={() => (message = '')}
				>Fermer</button
			>
		</div>{/if}
	{#if curriculum}
		{#key curriculumId}<CompetencyCanvas
				{graphs}
				{subjects}
				{pending}
				expandId={editor?.parentId}
				active={curriculum.is_active}
				onload={(id) => {
					void loadSubject(id);
				}}
				onopen={(subjectId, node) => (editor = { subjectId, node })}
				onadd={(subjectId, parentId) => {
					void add(subjectId, parentId);
				}}
			/>{/key}
	{:else}<div class="curricula-empty">
			<Icon name="book" size={42} />
			<h2 class="title is-4">Un référentiel, toutes ses matières.</h2>
			<p class="muted">
				{catalog.can_manage
					? 'Créez directement votre référentiel et choisissez les matières de son programme.'
					: 'Les référentiels apparaîtront ici dès leur création par un administrateur.'}
			</p>
			{#if catalog.can_manage}<button
					class="button is-primary mt-4"
					onclick={() => (settings = 'new')}><Icon name="plus" />Créer un référentiel</button
				>{/if}
		</div>{/if}
</section>
{#if settings}<CurriculumEditor
		{catalog}
		curriculum={settings === 'new' ? undefined : settings}
		onclose={() => (settings = null)}
		onsaved={(result) => {
			void saved(result);
		}}
	/>{/if}
{#if editor && editingGraph}{#key `${editor.subjectId}-${editor.node?.id ?? 'new'}-${editor.parentId ?? ''}`}<CompetencyEditor
			graph={editingGraph}
			node={editor.node}
			parentId={editor.parentId}
			{editable}
			onclose={() => (editor = null)}
			onsaved={acceptEdit}
			onchild={(parentId) => {
				if (editor) editor = { subjectId: editor.subjectId, parentId };
			}}
		/>{/key}{/if}

{#if transferMode && curriculum}{#key curriculumId}<CompetencyTransfer
			mode={transferMode}
			{curriculumId}
			subjects={transferMode === 'import'
				? subjects.filter((s) => s.can_edit && s.is_active)
				: subjects}
			onclose={() => (transferMode = null)}
			onsaved={acceptEdit}
		/>{/key}{/if}

<style>
	.curricula-page {
		width: 100%;
		padding: 0.75rem 1rem 1rem;
	}
	.curricula-heading {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.7rem;
		min-height: 48px;
		margin-bottom: 0.6rem;
	}
	.heading-title {
		display: flex;
		align-items: center;
		gap: 0.55rem;
		margin-right: 0.6rem;
		color: var(--color-primary);
	}
	h1 {
		font-size: 1.1rem;
		font-weight: 700;
		color: var(--color-ink);
	}
	.heading-actions {
		display: flex;
		gap: 0.5rem;
		margin-left: auto;
	}
	.curriculum-description {
		font-size: 0.8rem;
		max-width: 100ch;
		margin-bottom: 0.7rem;
		white-space: pre-line;
	}
	.curricula-empty {
		min-height: 70vh;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 1rem;
		padding: 2rem;
		text-align: center;
	}
	@media (max-width: 650px) {
		.curricula-page {
			padding: 0.5rem;
		}
		.heading-title {
			flex: 1;
		}
		.heading-actions {
			width: 100%;
			justify-content: flex-end;
		}
		.select {
			max-width: 60vw;
		}
		.select select {
			width: 100%;
		}
	}
</style>
