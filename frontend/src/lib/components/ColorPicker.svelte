<script lang="ts">
	let {
		value = $bindable('#4361EE'),
		id,
		label = 'Couleur',
		disabled = false
	}: { value: string; id: string; label?: string; disabled?: boolean } = $props();
</script>

<div class="field">
	<label class="label" for={id}>{label}</label>
	<div class="color-picker">
		<input {id} type="color" bind:value {disabled} aria-label="Choisir une couleur" />
		<input
			class="input"
			aria-label="Code couleur hexadécimal"
			bind:value
			{disabled}
			pattern={'#[0-9A-Fa-f]{6}'}
			maxlength="7"
			required
		/>
		<span
			class="color-preview"
			style:background={/^#[0-9a-f]{6}$/i.test(value) ? value : '#4361EE'}
			aria-hidden="true"
		></span>
	</div>
</div>
