<script lang="ts">
	import { onMount } from 'svelte';
	import { invalidateAll } from '$app/navigation';
	import { command, read } from '#lib/dashboard';
	import type { PublicSite } from '#lib/site';
	import TextEditor from '../TextEditor.svelte';
	import ColorPicker from '../ColorPicker.svelte';
	import CalendarSubscriptionAdmin from './CalendarSubscriptionAdmin.svelte';
	let site = $state<PublicSite | null>(null),
		name = $state(''),
		text = $state(''),
		color = $state('#244bc1');
	let loading = $state(true),
		busy = $state(false),
		message = $state(''),
		success = $state('');
	async function load(): Promise<void> {
		loading = true;
		try {
			site = await read<PublicSite>('site');
			name = site.settings.name;
			text = site.settings.home_text;
			color = site.settings.text_color;
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			loading = false;
		}
	}
	onMount(() => {
		void load();
	});
	async function save(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		if (!site) return;
		busy = true;
		message = '';
		success = '';
		try {
			await command('saveSettings', {
				data: {
					name,
					home_text: text,
					text_color: color,
					expected_version: site.settings.version
				}
			});
			await load();
			await invalidateAll();
			success = 'Configuration enregistrée. Les changements sont appliqués sans redémarrage.';
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
</script>

<div class="section-intro">
	<div>
		<p class="eyebrow">Configuration</p>
		<h2 class="title is-3">Votre site</h2>
		<p class="muted">Nom et présentation de votre établissement.</p>
	</div>
</div>
{#if message}<p class="notification is-danger is-light" role="alert">
		{message}
	</p>{/if}{#if success}<p class="notification is-success is-light" role="status">{success}</p>{/if}
{#if loading && !site}<p role="status">Chargement de la configuration…</p>{/if}
{#if site}<form class="workspace-panel" onsubmit={save}>
		<fieldset disabled={busy}>
			<div class="field">
				<label class="label" for="site-name">Nom du site</label><input
					id="site-name"
					class="input"
					bind:value={name}
					maxlength="100"
					required
				/>
			</div>
			<ColorPicker
				id="home-color"
				label="Couleur des passages mis en évidence"
				bind:value={color}
				disabled={busy}
			/>
			<div class="field">
				<label class="label" for="home-text">Texte d’accueil</label><TextEditor
					id="home-text"
					bind:value={text}
					{color}
					disabled={busy}
				/>
			</div>
			<p class="help mb-4">Ce texte est visible par tous, même sans connexion.</p>
			<button class="button is-primary" class:is-loading={busy}>Enregistrer la configuration</button
			>
		</fieldset>
	</form>
	<CalendarSubscriptionAdmin />{/if}
