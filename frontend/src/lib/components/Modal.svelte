<script lang="ts">
	import { onMount, type Snippet } from 'svelte';
	import { page } from '$app/state';
	import Icon from './Icon.svelte';
	let {
		title,
		description,
		drawer = false,
		busy = false,
		onclose,
		actions,
		children
	}: {
		title: string;
		description?: string;
		drawer?: boolean;
		busy?: boolean;
		onclose: () => void;
		actions?: Snippet;
		children: Snippet;
	} = $props();
	let dialog: HTMLDialogElement;
	const titleId = $props.id();
	onMount(() => {
		const previous = document.activeElement;
		dialog.showModal();
		const overflow = document.body.style.overflow;
		document.body.style.overflow = 'hidden';
		return () => {
			dialog.close();
			document.body.style.overflow = overflow;
			if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
		};
	});
</script>

<dialog
	bind:this={dialog}
	class="workspace-dialog"
	class:drawer
	aria-labelledby={titleId}
	oncancel={(event) => {
		event.preventDefault();
		if (!busy) onclose();
	}}
>
	<header class="dialog-header">
		<div>
			<p class="eyebrow">{page.data.establishmentName}</p>
			<h2 id={titleId} class="title is-4 mb-2">{title}</h2>
			{#if description}<p class="muted text-small">{description}</p>{/if}
		</div>
		<button
			class="icon-button"
			type="button"
			aria-label="Fermer la fenêtre"
			disabled={busy}
			onclick={onclose}><Icon name="close" /></button
		>
	</header>
	{#if actions}<div class="dialog-toolbar">{@render actions()}</div>{/if}
	<div class="dialog-body">{@render children()}</div>
</dialog>

<style>
	.dialog-toolbar {
		flex-shrink: 0;
		padding: 0.75rem 1.7rem;
		border-bottom: var(--border-thin);
		background: var(--color-surface);
	}
</style>
