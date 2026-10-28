<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { command, read } from '#lib/dashboard';
	import type { Subject } from '#lib/site';
	import type { Page } from '#lib/types';
	import Icon from '../Icon.svelte';
	import Pagination from '../Pagination.svelte';
	import SubjectEditor from './SubjectEditor.svelte';
	let { initialSubject }: { initialSubject?: Subject } = $props();
	let items = $state<Subject[]>([]),
		total = $state(0),
		offset = $state(0);
	let query = $state(''),
		filterState = $state('true'),
		loading = $state(true),
		busy = $state(false),
		ready = $state(false),
		revision = $state(0);
	let message = $state(''),
		selected = $state<Subject | null>(untrack(() => initialSubject ?? null)),
		editor = $state<Subject | 'new' | null>(null),
		confirmArchive = $state(false);
	onMount(() => {
		ready = true;
	});
	$effect(() => {
		const q = query,
			filter = filterState,
			page = offset;
		void revision;
		if (!ready) return;
		const controller = new AbortController();
		const timer = setTimeout(
			async () => {
				loading = true;
				message = '';
				try {
					const result = await read<Page<Subject>>(
						'subjects',
						{ q, is_active: filter || undefined, offset: page, limit: 12 },
						controller.signal
					);
					items = result.items;
					total = result.total;
				} catch (cause) {
					if (!controller.signal.aborted) message = (cause as Error).message;
				} finally {
					if (!controller.signal.aborted) loading = false;
				}
			},
			q ? 220 : 0
		);
		return () => {
			clearTimeout(timer);
			controller.abort();
		};
	});
	async function archive(): Promise<void> {
		if (!selected) return;
		busy = true;
		message = '';
		try {
			await command('archiveSubject', {
				id: selected.id,
				data: { expected_version: selected.version }
			});
			selected = null;
			confirmArchive = false;
			revision += 1;
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
</script>

<section class="workspace-panel">
	<div class="panel-heading">
		<div>
			<p class="eyebrow">Matières</p>
			<h2 class="title is-4 mb-2">Vos enseignements, au même endroit.</h2>
			<p class="muted text-small">
				Créez, organisez et retrouvez vos matières. Le compteur d’enseignants regroupe les
				professeurs et les khôlleurs uniques affectés à chaque matière.
			</p>
		</div>
		<button class="button is-primary" onclick={() => (editor = 'new')}
			><Icon name="plus" />Nouvelle matière</button
		>
	</div>
	{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
	{#if selected}
		<button
			class="button is-text mb-4"
			onclick={() => {
				selected = null;
				confirmArchive = false;
			}}><Icon name="previous" />Toutes les matières</button
		>
		<div class="promotion-detail" style:--promotion-color={selected.color}>
			<div>
				<span class="eyebrow">{selected.is_active ? 'Matière active' : 'Matière archivée'}</span>
				<h3 class="title is-3 entity-title">
					<Icon name={selected.icon} size={28} />{selected.name}
				</h3>
				<p class="muted">
					{selected.teacher_count} enseignant{selected.teacher_count === 1 ? '' : 's'} · {selected.lesson_count}
					cours
				</p>
			</div>
			{#if selected.is_active}<div class="profile-buttons">
					<button class="button is-light" onclick={() => (editor = selected)}
						><Icon name="edit" />Modifier</button
					><button class="button is-light" onclick={() => (confirmArchive = !confirmArchive)}
						><Icon name="archive" />Archiver</button
					>
				</div>{/if}
		</div>
		{#if confirmArchive}<div class="confirmation-panel mt-4">
				<p>
					Archiver « {selected.name} » ? La matière sera retirée des enseignants. L’opération sera refusée
					si un cours l’utilise.
				</p>
				<div class="buttons mt-3">
					<button
						class="button is-primary"
						disabled={busy}
						class:is-loading={busy}
						onclick={archive}>Confirmer</button
					><button class="button is-light" disabled={busy} onclick={() => (confirmArchive = false)}
						>Annuler</button
					>
				</div>
			</div>{/if}
	{:else}
		<div class="list-toolbar">
			<div class="search-field">
				<Icon name="search" /><input
					class="input"
					aria-label="Rechercher une matière"
					placeholder="Rechercher une matière…"
					maxlength="100"
					bind:value={query}
					oninput={() => (offset = 0)}
				/>
			</div>
			<div class="select">
				<select
					aria-label="État des matières"
					bind:value={filterState}
					onchange={() => (offset = 0)}
					><option value="true">Actives</option><option value="false">Archivées</option><option
						value="">Toutes les matières</option
					></select
				>
			</div>
		</div>
		{#if loading}<p class="loading-state" role="status">
				Chargement des matières…
			</p>{:else if !items.length}<div class="empty-state">
				<Icon name="book" size={30} />
				<p>Aucune matière à afficher.</p>
			</div>{:else}<div class="promotion-grid">
				{#each items as subject (subject.id)}<button
						class="promotion-card subject-card"
						style:--promotion-color={subject.color}
						onclick={() => {
							selected = subject;
							message = '';
						}}
						><span class="promotion-card-top"
							><Icon name={subject.icon} size={22} /><Icon name="open" size={14} /></span
						><strong>{subject.name}</strong><span class="muted text-small"
							>{subject.teacher_count} enseignant{subject.teacher_count === 1 ? '' : 's'} · {subject.lesson_count}
							cours · {subject.is_active ? 'Active' : 'Archivée'}</span
						></button
					>{/each}
			</div>{/if}
		<Pagination {offset} limit={12} {total} busy={loading} onchange={(value) => (offset = value)} />
	{/if}
</section>
{#if editor}<SubjectEditor
		subject={editor === 'new' ? undefined : editor}
		onclose={() => (editor = null)}
		onsaved={(subject) => {
			if (selected?.id === subject.id)
				selected = {
					...subject,
					teacher_count: selected.teacher_count,
					lesson_count: selected.lesson_count
				};
			revision += 1;
		}}
	/>{/if}
