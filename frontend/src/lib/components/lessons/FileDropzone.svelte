<script lang="ts">
	import Icon from '../Icon.svelte';
	let {
		file,
		accept,
		disabled = false,
		onselect
	}: {
		file: File | null;
		accept: string;
		disabled?: boolean;
		onselect: (file: File) => void;
	} = $props();
	let input: HTMLInputElement;
	let dragging = $state(false);
	let message = $state('');
	function choose(files: FileList | null): void {
		if (disabled || !files?.length) return;
		message = files.length > 1 ? 'Déposez un seul document à la fois.' : '';
		if (files.length === 1) onselect(files[0]);
	}
</script>

<div
	class="dropzone"
	class:dragging
	class:disabled
	role="group"
	aria-label="Dépôt de document"
	ondragover={(event) => {
		event.preventDefault();
		if (!disabled) dragging = true;
	}}
	ondragleave={(event) => {
		if (!event.currentTarget.contains(event.relatedTarget as Node)) dragging = false;
	}}
	ondrop={(event) => {
		event.preventDefault();
		dragging = false;
		choose(event.dataTransfer?.files ?? null);
	}}
>
	<input
		bind:this={input}
		class="is-sr-only"
		type="file"
		{accept}
		{disabled}
		aria-label="Choisir un fichier"
		onchange={(event) => choose(event.currentTarget.files)}
	/>
	<button type="button" {disabled} onclick={() => input.click()}>
		<Icon name={file ? 'check' : 'upload'} size={30} />
		<strong>{file?.name ?? 'Déposez votre document ici'}</strong>
		<span>{file ? 'Cliquer pour remplacer' : 'ou cliquez pour choisir un fichier'}</span>
	</button>
</div>
{#if message}<p class="help is-danger" role="alert">{message}</p>{/if}

<style>
	.dropzone {
		border: 1px dashed var(--color-primary);
		border-radius: 1rem;
		background: var(--color-soft);
	}
	.dropzone.dragging {
		outline: 3px solid var(--color-primary);
		outline-offset: 3px;
	}
	.dropzone.disabled {
		opacity: 0.6;
	}
	button {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.55rem;
		padding: 1.7rem 1rem;
		width: 100%;
		border: 0;
		border-radius: inherit;
		background: transparent;
		color: var(--color-primary);
		font: inherit;
		cursor: pointer;
	}
	button:disabled {
		cursor: default;
	}
	strong {
		color: var(--color-ink);
		font-size: 0.9rem;
		max-width: 100%;
		overflow-wrap: anywhere;
	}
	span {
		color: var(--color-muted);
		font-size: 0.8rem;
	}
</style>
