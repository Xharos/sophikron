<script lang="ts">
	import { goto, invalidateAll } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { onMount, untrack } from 'svelte';
	import {
		colorForeground,
		lessonCommand,
		LessonError,
		lessonTeam,
		type ElementKind,
		type LessonDetail,
		type LessonElement
	} from '#lib/lessons';
	import CourseEditor from '#lib/components/lessons/CourseEditor.svelte';
	import ElementEditor from '#lib/components/lessons/ElementEditor.svelte';
	import FileEditor from '#lib/components/lessons/FileEditor.svelte';
	import LessonContent from '#lib/components/lessons/LessonContent.svelte';
	import LessonSettings from '#lib/components/lessons/LessonSettings.svelte';
	import ResponsibilityEditor from '#lib/components/lessons/ResponsibilityEditor.svelte';
	import Modal from '#lib/components/Modal.svelte';
	import StatisticsPanel from '#lib/components/statistics/StatisticsPanel.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import RoleTag from '#lib/components/RoleTag.svelte';
	import type { PageProps } from './$types';
	let { data }: PageProps = $props();
	let lesson = $state<LessonDetail>(untrack(() => data.lesson));
	let editing = $state(false);
	let metadata = $state(false);
	let settings = $state(false);
	let statisticsOpen = $state(false);
	let responsibility = $state(false);
	let editor = $state<{
		element: LessonElement | null;
		kind: ElementKind;
		parent: LessonElement | null;
		rowIndex: number | null;
		columnIndex: number | null;
	} | null>(null);
	let removing = $state<LessonElement | null>(null);
	let deletingCourse = $state(false);
	let busy = $state(false);
	let message = $state('');
	let success = $state('');
	$effect(() => {
		lesson = data.lesson;
		if (!data.lesson.can_edit) {
			editing = false;
			metadata = false;
			settings = false;
			editor = null;
			removing = null;
		}
		if (!data.lesson.can_transfer) responsibility = false;
		if (!data.lesson.can_view_statistics) statisticsOpen = false;
	});
	const headings = $derived(
		lesson.elements.filter((item) => item.kind === 'section' || item.kind === 'subsection')
	);
	const team = $derived(lessonTeam(lesson));
	function received(updated: LessonDetail): void {
		lesson = updated;
		message = '';
		success = 'Modifications enregistrées.';
	}
	function saved(updated: LessonDetail): void {
		received(updated);
		metadata = false;
		editor = null;
	}
	function add(
		kind: ElementKind,
		parent: LessonElement | null,
		row?: number,
		column?: number
	): void {
		editor = { element: null, kind, parent, rowIndex: row ?? null, columnIndex: column ?? null };
	}
	function edit(element: LessonElement): void {
		editor = {
			element,
			kind: element.kind,
			rowIndex: element.row_index,
			columnIndex: element.column_index,
			parent: lesson.elements.find((item) => item.id === element.parent_id) ?? null
		};
	}
	async function mutate(
		command: string,
		element: LessonElement,
		extra: object = {}
	): Promise<void> {
		busy = true;
		message = '';
		success = '';
		try {
			received(
				await lessonCommand<LessonDetail>(command, {
					lessonId: lesson.id,
					elementId: element.id,
					data: { expected_version: lesson.version, ...extra }
				})
			);
			removing = null;
		} catch (cause) {
			message = (cause as Error).message;
			if (cause instanceof LessonError && [401, 403].includes(cause.status)) {
				editing = false;
				removing = null;
				await invalidateAll();
			}
		} finally {
			busy = false;
		}
	}
	async function refresh(): Promise<void> {
		busy = true;
		message = '';
		try {
			await invalidateAll();
		} catch {
			message = 'Le cours n’a pas pu être actualisé.';
		} finally {
			busy = false;
		}
	}
	async function toggleEditing(): Promise<void> {
		if (editing) {
			editing = false;
			return;
		}
		busy = true;
		try {
			await invalidateAll();
			editing = data.lesson.can_edit;
			success = '';
		} catch {
			message = 'Les droits d’édition n’ont pas pu être vérifiés.';
		} finally {
			busy = false;
		}
	}
	onMount(() => {
		const revoked = (): void => {
			editing = false;
			metadata = false;
			settings = false;
			editor = null;
			removing = null;
			void invalidateAll();
		};
		window.addEventListener('lesson-access-revoked', revoked);
		return () => window.removeEventListener('lesson-access-revoked', revoked);
	});
</script>

<svelte:head
	><title>{lesson.title} — {data.establishmentName}</title><meta
		name="description"
		content={lesson.description}
	/><meta name="robots" content="noindex, nofollow" /></svelte:head
>
<section
	class="section container dashboard lesson-page"
	class:student-view={!lesson.staff_view}
	style:--lesson-color={lesson.color}
>
	<a class="course-back" href={resolve('/lessons')}
		><Icon name="previous" size={14} />Tous les cours</a
	>
	<header class="lesson-header">
		<span
			class="lesson-symbol"
			style:background={lesson.color}
			style:color={colorForeground(lesson.color)}><Icon name={lesson.icon} size={34} /></span
		>
		<div>
			<p class="eyebrow">{lesson.subject_name}</p>
			<h1 class="title is-3 mb-2">{lesson.title}</h1>
			<p class="lesson-description">{lesson.description}</p>
			{#each [team.teachers, team.kholleurs] as people, index (index)}{#if people.length}<div
						class="lesson-team"
					>
						{#each people as person (person.id)}<RoleTag
								role={person.role === 'teacher' || person.role === 'kholleur' ? person.role : null}
								label={person.label}
							/>{/each}
					</div>{/if}{/each}
		</div>
	</header>
	<div class="lesson-toolbar">
		{#if lesson.staff_view}<span class="mode-label"
				><Icon name={editing ? 'edit' : 'book'} size={16} />{editing
					? 'Mode édition'
					: 'Mode lecture'}</span
			>{/if}
		<div>
			{#if lesson.can_view_statistics}<button
					class="button is-light is-small"
					onclick={() => (statisticsOpen = !statisticsOpen)}
					aria-expanded={statisticsOpen}
					><Icon name="overview" size={14} />Statistiques du cours</button
				>{/if}
			<button
				class="button is-light is-small"
				title="Actualiser"
				aria-label="Actualiser le cours"
				disabled={busy || !!editor || metadata || settings}
				onclick={refresh}><Icon name="restore" size={14} /></button
			>{#if lesson.can_edit}<button
					class="button is-primary is-small"
					disabled={busy}
					onclick={toggleEditing}
					><Icon name={editing ? 'book' : 'edit'} size={14} />{editing
						? 'Revenir à la lecture'
						: 'Modifier le cours'}</button
				>{/if}
		</div>
	</div>
	{#if message}<p class="notification is-danger is-light" role="alert">
			{message}
		</p>{/if}{#if success}<p class="save-status" role="status">
			<Icon name="check" size={14} />{success}
		</p>{/if}
	{#if editing}<div class="editing-toolbar">
			<div>
				<button class="button is-light is-small" onclick={() => (metadata = true)} disabled={busy}
					>Informations du cours</button
				><button class="button is-light is-small" onclick={() => (settings = true)} disabled={busy}
					><Icon name="accounts" size={14} />Accès et collaborateurs</button
				>
				{#if lesson.can_manage_collaborators}<button
						class="button is-danger is-light is-small"
						disabled={busy}
						onclick={() => (deletingCourse = true)}>Supprimer le cours</button
					>{/if}
				{#if lesson.can_transfer}<button
						class="button is-warning is-light is-small"
						onclick={() => (responsibility = true)}
						disabled={busy}>Réaffecter le responsable / la matière</button
					>{/if}
			</div>
		</div>
		{#if lesson.warnings.length}<details class="course-warnings">
				<summary
					>{lesson.warnings.length} point{lesson.warnings.length === 1 ? '' : 's'} à vérifier</summary
				>
				<ul>
					{#each lesson.warnings as warning, index (index)}<li>{warning}</li>{/each}
				</ul>
			</details>{/if}{/if}
	{#if statisticsOpen && lesson.can_view_statistics}<StatisticsPanel lessonId={lesson.id} />{/if}
	<div class="lesson-layout">
		<aside class="lesson-outline">
			<details open={lesson.staff_view}>
				<summary>Dans ce cours</summary>
				<nav aria-label="Sommaire du cours">
					{#each headings as heading (heading.id)}<a
							class:subheading={heading.kind === 'subsection'}
							href={`#element-${heading.id}`}>{heading.title}</a
						>{/each}{#if !headings.length}<p class="muted text-small">
							Le programme sera bientôt disponible.
						</p>{/if}
				</nav>
			</details>
		</aside>
		<LessonContent
			{lesson}
			{editing}
			{busy}
			onedit={edit}
			onupdate={received}
			onadd={add}
			onremove={(element) => (removing = element)}
			onmove={(element, direction) => mutate('moveElement', element, { direction })}
		/>
	</div>
</section>
{#if metadata}<CourseEditor {lesson} onsaved={saved} onclose={() => (metadata = false)} />{/if}
{#if editor?.kind === 'file' && editor.parent}<FileEditor
		{lesson}
		element={editor.element}
		parent={editor.parent}
		rowIndex={editor.rowIndex}
		columnIndex={editor.columnIndex}
		onsaved={saved}
		onclose={() => (editor = null)}
	/>{:else if editor}<ElementEditor
		{lesson}
		{...editor}
		onsaved={saved}
		onclose={() => (editor = null)}
	/>{/if}
{#if settings}<LessonSettings {lesson} onsaved={received} onclose={() => (settings = false)} />{/if}
{#if responsibility && lesson.can_transfer}<ResponsibilityEditor
		{lesson}
		onsaved={received}
		onclose={() => (responsibility = false)}
	/>{/if}
{#if deletingCourse}<Modal
		title="Supprimer le cours ?"
		description="Toutes les sections, tableaux et ressources seront supprimés définitivement."
		{busy}
		onclose={() => (deletingCourse = false)}
		><p>Supprimer « {lesson.title} » et tous ses documents ?</p>
		<div class="dialog-actions">
			<button class="button is-light" disabled={busy} onclick={() => (deletingCourse = false)}
				>Annuler</button
			><button
				class="button is-danger"
				disabled={busy}
				onclick={async () => {
					busy = true;
					try {
						await lessonCommand('removeLesson', {
							lessonId: lesson.id,
							data: { expected_version: lesson.version }
						});
						await goto(resolve('/lessons'));
					} catch (cause) {
						message = (cause as Error).message;
						deletingCourse = false;
					} finally {
						busy = false;
					}
				}}>Supprimer définitivement</button
			>
		</div></Modal
	>{/if}
{#if removing}<Modal
		title="Supprimer cet élément ?"
		description="Les éléments enfants seront également supprimés. Cette opération ne peut pas être annulée."
		{busy}
		onclose={() => (removing = null)}
		><p>Supprimer « {removing.title || 'cet élément'} » et son contenu ?</p>
		<div class="dialog-actions">
			<button class="button is-light" disabled={busy} onclick={() => (removing = null)}
				>Annuler</button
			><button
				class="button is-danger"
				class:is-loading={busy}
				disabled={busy}
				onclick={() => {
					if (removing) void mutate('removeElement', removing);
				}}>Supprimer</button
			>
		</div></Modal
	>{/if}

<style>
	.student-view .lesson-layout {
		grid-template-columns: minmax(0, 1fr);
		gap: 0.6rem;
	}
	.student-view .lesson-outline {
		position: static;
	}
	.student-view .lesson-toolbar {
		justify-content: flex-end;
		padding: 0.4rem 0;
	}
	.course-back {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		font-size: 0.85rem;
		color: var(--color-muted);
		margin-bottom: 2rem;
	}
	.lesson-header {
		display: flex;
		gap: 1.5rem;
		align-items: start;
		margin-bottom: 2rem;
	}
	.lesson-header > div {
		min-width: 0;
	}
	.lesson-header h1 {
		overflow-wrap: anywhere;
	}
	.lesson-symbol {
		width: 52px;
		height: 52px;
		border-radius: 16px;
		flex-shrink: 0;
		display: grid;
		place-items: center;
	}
	.lesson-description {
		max-width: 760px;
		color: var(--color-muted);
		line-height: 1.7;
		overflow-wrap: anywhere;
	}
	.lesson-team {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
		align-items: center;
		margin-top: 0.65rem;
		font-size: 0.83rem;
	}
	.lesson-toolbar,
	.editing-toolbar {
		display: flex;
		gap: 1rem;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		padding: 1rem 0;
		border-top: var(--border-thin);
	}
	.lesson-toolbar > div,
	.editing-toolbar > div {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
	}
	.mode-label,
	.save-status {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		font-size: 0.8rem;
		font-weight: 600;
		color: var(--color-muted);
	}
	.save-status {
		color: var(--color-success);
		margin-bottom: 0.7rem;
	}
	.lesson-layout {
		display: grid;
		grid-template-columns: 215px minmax(0, 1fr);
		gap: 2rem;
		margin-top: 1rem;
		align-items: start;
	}
	.lesson-outline {
		position: sticky;
		top: 1.5rem;
	}
	.lesson-outline summary {
		font-weight: 650;
		padding: 0.7rem 0;
		cursor: pointer;
	}
	.lesson-outline nav {
		display: grid;
		gap: 0.2rem;
		padding-top: 0.5rem;
	}
	.lesson-outline a {
		color: var(--color-muted);
		font-size: 0.82rem;
		padding: 0.5rem 0.7rem;
		border-radius: 0.4rem;
		overflow-wrap: anywhere;
	}
	.lesson-outline a:hover {
		background: var(--color-soft);
		color: var(--color-primary);
	}
	.lesson-outline a.subheading {
		padding-left: 1.5rem;
		font-size: 0.77rem;
	}
	.course-warnings {
		padding: 1rem;
		background: var(--color-warning-soft);
		border: 1px solid var(--color-border);
		border-radius: 0.6rem;
		margin-bottom: 1rem;
		font-size: 0.8rem;
		color: var(--color-warning);
	}
	.course-warnings summary {
		cursor: pointer;
		font-weight: 650;
	}
	.course-warnings ul {
		margin: 0.7rem 0 0 1.2rem;
		list-style: disc;
	}
	@media (max-width: 850px) {
		.lesson-layout {
			grid-template-columns: 1fr;
			gap: 1rem;
		}
		.lesson-outline {
			position: static;
			padding: 0.5rem 1rem;
			border: var(--border-thin);
			border-radius: 0.8rem;
		}
	}
	@media (max-width: 550px) {
		.lesson-header {
			gap: 1rem;
		}
		.lesson-symbol {
			width: 52px;
			height: 52px;
			border-radius: 16px;
		}
		.lesson-header h1 {
			font-size: 1.9rem;
		}
	}
</style>
