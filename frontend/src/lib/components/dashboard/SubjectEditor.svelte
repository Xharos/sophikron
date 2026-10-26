<script lang="ts">
	import { untrack } from 'svelte';
	import { command } from '#lib/dashboard';
	import { lessonIcons } from '#lib/lessons';
	import type { Subject } from '#lib/site';
	import Modal from '../Modal.svelte';
	import Icon from '../Icon.svelte';
	import ColorPicker from '../ColorPicker.svelte';
	import VisualPicker from '../VisualPicker.svelte';
	import SubjectTag from '../SubjectTag.svelte';
	let {
		subject,
		onclose,
		onsaved
	}: { subject?: Subject; onclose: () => void; onsaved: (subject: Subject) => void } = $props();
	const original = untrack(() => subject);
	let name = $state(original?.name ?? ''),
		icon = $state<Subject['icon']>(original?.icon ?? 'book'),
		color = $state(original?.color ?? '#4361EE');
	let busy = $state(false),
		message = $state('');
	async function save(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		busy = true;
		message = '';
		try {
			const saved = await command<Subject>(original ? 'updateSubject' : 'createSubject', {
				id: original?.id,
				data: { name, icon, color, ...(original ? { expected_version: original.version } : {}) }
			});
			onsaved(saved);
			onclose();
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
</script>

<Modal
	title={original ? 'Modifier la matière' : 'Nouvelle matière'}
	description="Une icône et une couleur partagées par tous ses cours."
	{busy}
	{onclose}
>
	{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
	<form onsubmit={save} aria-busy={busy}>
		<fieldset disabled={busy}>
			<div class="field">
				<label class="label" for="subject-name">Nom de la matière</label><input
					id="subject-name"
					class="input"
					bind:value={name}
					maxlength="100"
					required
				/>
			</div>
			<VisualPicker
				label="Icône"
				bind:value={icon}
				choices={lessonIcons.map((choice) => ({ ...choice, icon: choice.value }))}
			/>
			<ColorPicker id="subject-color" bind:value={color} />
			<div class="field">
				<p class="label">Aperçu de la matière</p>
				<SubjectTag
					subject={{
						name: name.trim() || 'Votre matière',
						icon,
						color: /^#[0-9a-f]{6}$/i.test(color) ? color : '#4361EE'
					}}
				/>
			</div>
			{#if original}<p class="help mb-4">
					L’icône et la couleur seront actualisées sur tous les cours de cette matière.
				</p>{/if}
			<div class="dialog-actions">
				<button type="button" class="button is-light" onclick={onclose}>Annuler</button><button
					class="button is-primary"
					class:is-loading={busy}><Icon name="check" />Enregistrer</button
				>
			</div>
		</fieldset>
	</form>
</Modal>
