<script lang="ts">
	import { onMount } from 'svelte';
	import {
		periodLabel,
		type ElementKind,
		type LessonDetail,
		type LessonElement
	} from '#lib/lessons';
	import Icon from '../Icon.svelte';
	import ResourceBody from './ResourceBody.svelte';
	import ResourceTable from './ResourceTable.svelte';
	let {
		lesson,
		editing,
		busy,
		onedit,
		onadd,
		onremove,
		onmove,
		onupdate
	}: {
		lesson: LessonDetail;
		editing: boolean;
		busy: boolean;
		onedit: (element: LessonElement) => void;
		onadd: (kind: ElementKind, parent: LessonElement | null, row?: number, column?: number) => void;
		onremove: (element: LessonElement) => void;
		onmove: (element: LessonElement, direction: 'up' | 'down') => void;
		onupdate: (lesson: LessonDetail) => void;
	} = $props();
	const sections = $derived(lesson.elements.filter((item) => item.kind === 'section'));
	let collapsed = $state<Record<number, boolean>>({});
	function children(item: LessonElement): LessonElement[] {
		return lesson.elements.filter((child) => child.parent_id === item.id);
	}
	function moveDisabled(item: LessonElement, direction: 'up' | 'down'): boolean {
		const siblings = lesson.elements.filter((sibling) => sibling.parent_id === item.parent_id);
		return busy || siblings.indexOf(item) === (direction === 'up' ? 0 : siblings.length - 1);
	}
	function isCollapsed(item: LessonElement): boolean {
		return collapsed[item.id] ?? (!editing && !lesson.staff_view && item.kind === 'section');
	}
	function toggle(item: LessonElement): void {
		collapsed[item.id] = !isCollapsed(item);
	}
	function revealHash(hash = window.location.hash): void {
		const id = Number(hash.replace('#element-', ''));
		let item = lesson.elements.find((element) => element.id === id);
		while (item) {
			collapsed[item.id] = false;
			const parentId = item.parent_id;
			item = lesson.elements.find((element) => element.id === parentId);
		}
	}
	onMount(() => revealHash());
</script>

<svelte:window
	onhashchange={() => revealHash()}
	onclick={(event) => {
		const anchor =
			event.target instanceof Element ? event.target.closest('a[href^="#element-"]') : null;
		if (anchor) revealHash(anchor.getAttribute('href') ?? '');
	}}
/>

{#snippet availability(item: LessonElement)}
	{#if lesson.staff_view && (item.effective_audience === 'staff' || item.effective_starts_on || item.effective_ends_on)}<p
			class="element-period"
		>
			{#if item.effective_audience === 'staff'}<span title="Équipe uniquement"
					><Icon name="teacher" size={13} /></span
				>{:else}<Icon name="clock" size={13} />{periodLabel(
					item.effective_starts_on,
					item.effective_ends_on
				)}{/if}
		</p>{/if}
{/snippet}
{#snippet controls(item: LessonElement)}
	{#if editing}<div
			class="element-controls"
			role="group"
			aria-label={`Actions : ${item.title || 'élément'}`}
		>
			{#if item.row_index === null}
				<button
					class="icon-button"
					title="Monter"
					aria-label={`Monter ${item.title || 'cet élément'}`}
					disabled={moveDisabled(item, 'up')}
					onclick={() => onmove(item, 'up')}><Icon name="up" size={13} /></button
				>
				<button
					class="icon-button"
					title="Descendre"
					aria-label={`Descendre ${item.title || 'cet élément'}`}
					disabled={moveDisabled(item, 'down')}
					onclick={() => onmove(item, 'down')}><Icon name="down" size={13} /></button
				>
			{/if}
			<button
				class="icon-button"
				title="Modifier"
				aria-label={`Modifier ${item.title || 'cet élément'}`}
				disabled={busy}
				onclick={() => onedit(item)}><Icon name="edit" size={13} /></button
			>
			<button
				class="icon-button"
				title="Supprimer"
				aria-label={`Supprimer ${item.title || 'cet élément'}`}
				disabled={busy}
				onclick={() => onremove(item)}><Icon name="remove" size={13} /></button
			>
		</div>{/if}
{/snippet}
{#snippet additions(parent: LessonElement)}
	{#if editing}<div class="element-additions">
			{#each [{ kind: 'subsection', label: 'Sous-section', icon: 'plus' }, { kind: 'text', label: 'Texte', icon: 'edit' }, { kind: 'youtube', label: 'Vidéo', icon: 'video' }, { kind: 'file', label: 'Document', icon: 'upload' }, { kind: 'table', label: 'Tableau', icon: 'table' }] as choice (choice.kind)}
				{#if choice.kind !== 'subsection' || parent.kind === 'section'}<button
						class="button is-light is-small"
						disabled={busy}
						onclick={() => onadd(choice.kind as ElementKind, parent)}
						><Icon name={choice.icon} size={13} />{choice.label}</button
					>{/if}
			{/each}
		</div>{/if}
{/snippet}
{#snippet leaf(item: LessonElement)}
	<article id={`element-${item.id}`} class="lesson-leaf">
		{#if editing || (item.title && item.kind !== 'file' && item.kind !== 'youtube')}<div
				class="element-heading"
			>
				{#if item.title && item.kind !== 'file' && item.kind !== 'youtube'}<h4
						class="title is-6 mb-0"
					>
						{item.title}
					</h4>{/if}{@render controls(item)}
			</div>{/if}
		{@render availability(item)}
		{#if item.kind === 'table'}<ResourceTable
				table={item}
				{lesson}
				{editing}
				{busy}
				{onedit}
				{onadd}
				{onremove}
				{onupdate}
			/>{:else}<ResourceBody
				{item}
				lessonId={lesson.id}
				color={lesson.color}
				staffView={lesson.staff_view}
			/>{/if}
	</article>
{/snippet}

<div class="lesson-content" class:student-view={!lesson.staff_view}>
	{#each sections as section (section.id)}
		<section id={`element-${section.id}`} class="lesson-section workspace-panel">
			<div class="element-heading">
				<h2 class="title is-5 mb-0">
					<button
						class="section-toggle"
						aria-expanded={!isCollapsed(section)}
						aria-controls={`children-${section.id}`}
						onclick={() => toggle(section)}
						><span class:folded={isCollapsed(section)}><Icon name="chevron" size={14} /></span
						>{section.title}</button
					>
				</h2>
				{@render controls(section)}
			</div>
			{@render availability(section)}
			<div id={`children-${section.id}`} hidden={isCollapsed(section)}>
				<div class="section-children">
					{#each children(section) as item (item.id)}
						{#if item.kind === 'subsection'}<section
								id={`element-${item.id}`}
								class="lesson-subsection"
							>
								<div class="element-heading">
									<h3 class="title is-6 mb-0">
										<button
											class="section-toggle"
											aria-expanded={!isCollapsed(item)}
											aria-controls={`children-${item.id}`}
											onclick={() => toggle(item)}
											><span class:folded={isCollapsed(item)}
												><Icon name="chevron" size={12} /></span
											>{item.title}</button
										>
									</h3>
									{@render controls(item)}
								</div>
								<div id={`children-${item.id}`} hidden={isCollapsed(item)}>
									{#each children(item) as child (child.id)}{@render leaf(
											child
										)}{/each}{@render additions(item)}
								</div>
							</section>{:else}{@render leaf(item)}{/if}
					{/each}
				</div>
				{@render additions(section)}
			</div>
		</section>
	{/each}
	{#if !sections.length}<p class="empty-state">
			{editing ? 'Ajoutez votre première section.' : 'Le contenu arrive bientôt.'}
		</p>{/if}
	{#if editing}<button
			class="button is-light is-fullwidth"
			aria-label="Ajouter une section"
			disabled={busy}
			onclick={() => onadd('section', null)}><Icon name="plus" />Section</button
		>{/if}
</div>

<style>
	.lesson-content {
		min-width: 0;
	}
	.lesson-section {
		padding: 1.1rem 1.3rem;
		margin-bottom: 0.8rem;
		scroll-margin-top: 1rem;
	}
	.element-heading {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.7rem;
		flex-wrap: wrap;
	}
	.element-controls {
		display: flex;
		gap: 0.25rem;
		flex-wrap: wrap;
		margin-left: auto;
	}
	.element-period {
		display: flex;
		align-items: center;
		gap: 0.35rem;
		font-size: 0.7rem;
		color: var(--color-muted);
		margin: 0.4rem 0;
	}
	.section-toggle {
		display: flex;
		gap: 0.7rem;
		align-items: center;
		border: 0;
		background: transparent;
		padding: 0.2rem 0;
		color: var(--color-ink);
		text-align: left;
		font: inherit;
		cursor: pointer;
		overflow-wrap: anywhere;
	}
	.section-toggle > span {
		display: inline-flex;
		color: var(--color-muted);
		transition: transform 150ms ease;
	}
	.section-toggle > span.folded {
		transform: rotate(-90deg);
	}
	.section-children {
		margin-top: 0.8rem;
	}
	.lesson-subsection {
		border-left: 2px solid var(--lesson-color, var(--color-border));
		padding-left: 1rem;
		margin: 1rem 0;
		scroll-margin-top: 1rem;
	}
	.lesson-leaf {
		padding: 0.65rem 0;
		scroll-margin-top: 1rem;
	}
	.lesson-leaf > .element-heading {
		margin-bottom: 0.45rem;
	}
	.element-additions {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
		margin-top: 0.8rem;
		padding-top: 0.7rem;
		border-top: var(--border-thin);
	}
	.student-view .lesson-leaf {
		padding: 0.4rem 0;
	}
	@media (max-width: 650px) {
		.lesson-section {
			padding: 0.9rem;
		}
		.lesson-subsection {
			padding-left: 0.65rem;
		}
	}
</style>
