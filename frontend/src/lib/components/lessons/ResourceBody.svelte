<script lang="ts">
	import { resolve } from '$app/paths';
	import { documentLabel, type LessonElement } from '#lib/lessons';
	import Icon from '../Icon.svelte';
	import FormattedText from './FormattedText.svelte';
	let {
		item,
		lessonId,
		color,
		staffView = false
	}: { item: LessonElement; lessonId: number; color: string; staffView?: boolean } = $props();
	let loaded = $state(false);
	const videoId = $derived(
		item.kind === 'youtube' && item.body ? (new URL(item.body).searchParams.get('v') ?? '') : ''
	);
	const fileName = $derived(
		item.file ? documentLabel(item.title || item.file.original_name, item.file.extension) : ''
	);
	const usable = $derived(item.available || staffView);
	$effect(() => {
		void item.id;
		void item.body;
		void item.available;
		loaded = false;
	});
</script>

{#if item.kind === 'text'}
	<FormattedText text={item.body} {color} />
{:else if !usable}
	<div class="resource-card unavailable" aria-disabled="true">
		<span class="resource-icon"
			><Icon
				name={item.kind === 'file' ? (item.file?.extension ?? 'book') : 'video'}
				size={26}
			/></span
		>
		<span class="resource-label"
			><strong>{item.kind === 'file' ? fileName : item.title || 'Vidéo'}</strong><small
				>{item.kind === 'file' ? item.file?.extension.toUpperCase() : 'YOUTUBE'}</small
			></span
		>
	</div>
{:else if item.kind === 'file' && item.file}
	<a
		class="resource-card"
		title={fileName}
		aria-label={`Télécharger ${fileName}`}
		href={resolve(`/lessons/download?lessonId=${lessonId}&fileId=${item.file.id}`)}
		download
	>
		<span class="resource-icon" class:pdf={item.file.extension === 'pdf'}
			><Icon name={item.file.extension} size={26} /></span
		>
		<span class="resource-label"
			><strong>{fileName}</strong><small>{item.file.extension.toUpperCase()}</small></span
		>
		<Icon name="download" size={16} />
	</a>
{:else if item.kind === 'youtube'}
	{#if loaded && videoId}<iframe
			class="video-player"
			title={item.title || 'Vidéo YouTube'}
			src={`https://www.youtube-nocookie.com/embed/${videoId}`}
			referrerpolicy="strict-origin-when-cross-origin"
			allow="encrypted-media; picture-in-picture; fullscreen"
			allowfullscreen
		></iframe>
	{:else}<button
			type="button"
			class="resource-card"
			title="Lire la vidéo YouTube"
			aria-label={`Lire ${item.title || 'la vidéo'}`}
			onclick={() => (loaded = true)}
			><span class="resource-icon"><Icon name="video" size={26} /></span><span
				class="resource-label"><strong>{item.title || 'Vidéo'}</strong><small>YOUTUBE</small></span
			><Icon name="arrow" size={16} /></button
		>{/if}
{/if}

<style>
	.resource-card {
		display: flex;
		align-items: center;
		gap: 0.8rem;
		width: 100%;
		min-width: 0;
		border: var(--border-thin);
		border-radius: 0.8rem;
		padding: 0.85rem;
		color: var(--color-ink);
		background: var(--color-surface);
		text-align: left;
		font: inherit;
	}
	a.resource-card:hover,
	button.resource-card:hover {
		background: var(--color-soft);
		border-color: var(--color-primary);
	}
	button.resource-card {
		cursor: pointer;
	}
	.resource-icon {
		display: grid;
		place-items: center;
		width: 38px;
		height: 38px;
		flex-shrink: 0;
		border-radius: 0.6rem;
		color: var(--color-info);
		background: var(--color-info-soft);
	}
	.resource-icon.pdf {
		color: var(--color-danger);
		background: var(--color-danger-soft);
	}
	.resource-label {
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
		min-width: 0;
		flex: 1;
	}
	strong {
		font-size: 0.87rem;
		overflow-wrap: anywhere;
	}
	small {
		color: var(--color-muted);
		font-size: 0.65rem;
		letter-spacing: 0.06em;
	}
	.unavailable {
		background: var(--color-subtle);
		color: var(--color-muted);
	}
	.unavailable strong {
		color: var(--color-muted);
	}
	.unavailable .resource-icon {
		filter: grayscale(1);
		background: var(--color-paper);
		color: var(--color-muted);
	}
	.video-player {
		display: block;
		width: 100%;
		aspect-ratio: 16 / 9;
		border: 0;
		border-radius: 0.8rem;
	}
</style>
