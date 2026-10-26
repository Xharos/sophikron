<script lang="ts">
	import { roleOptions } from '#lib/roles';
	import TagSelector from './TagSelector.svelte';
	let {
		selected = $bindable([]),
		disabled = false,
		preserveAdmin = false
	}: {
		selected: string[];
		disabled?: boolean;
		preserveAdmin?: boolean;
	} = $props();
</script>

<TagSelector
	legend="Rôles du compte"
	bind:selected
	{disabled}
	options={roleOptions.map((option) => ({
		...option,
		disabled: preserveAdmin && option.value === 'admin'
	}))}
/>
<p class="help">
	Élève est exclusif. Les rôles Khôlleur, Enseignant et Administrateur se cumulent librement.
</p>
{#if preserveAdmin}<p class="help">
		Vous ne pouvez pas retirer votre propre rôle Administrateur.
	</p>{/if}
