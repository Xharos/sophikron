<script lang="ts">
	import type { ScheduleMode, LessonElement, ElementKind } from '#lib/lessons';
	import Icon from '../Icon.svelte';
	let {
		mode = $bindable('inherit'),
		start = $bindable(''),
		end = $bindable(''),
		audience = $bindable('students'),
		parent,
		kind,
		disabled = false
	}: {
		mode: ScheduleMode;
		start: string;
		end: string;
		audience: 'students' | 'staff';
		parent: LessonElement | null;
		kind: ElementKind;
		disabled?: boolean;
	} = $props();
	const prefix = $props.id();
</script>

{#if kind === 'section'}
	<fieldset {disabled} class="policy-fields">
		<legend class="label">Visibilité</legend>
		<div class="visibility-options">
			<label
				><input type="radio" name={prefix} value="students" bind:group={audience} /><Icon
					name="student"
					size={16}
				/>Élèves et équipe</label
			>
			<label
				><input type="radio" name={prefix} value="staff" bind:group={audience} /><Icon
					name="teacher"
					size={16}
				/>Équipe uniquement</label
			>
		</div>
	</fieldset>
{:else if (kind === 'file' || kind === 'youtube') && parent?.effective_audience !== 'staff'}
	<fieldset {disabled} class="policy-fields">
		<legend class="label">Disponibilité</legend>
		<div class="field">
			<label class="is-sr-only" for={prefix + '-mode'}>Disponibilité</label>
			<div class="select is-fullwidth">
				<select id={prefix + '-mode'} bind:value={mode}
					><option value="inherit">Toujours disponible</option><option value="from"
						>À partir du…</option
					><option value="range">Du… au…</option></select
				>
			</div>
		</div>
		{#if mode !== 'inherit'}<div class="date-fields">
				<div class="field">
					<label class="label" for={prefix + '-start'}>Du</label><input
						class="input"
						id={prefix + '-start'}
						type="date"
						bind:value={start}
						required
					/>
				</div>
				{#if mode === 'range'}<div class="field">
						<label class="label" for={prefix + '-end'}>Au</label><input
							class="input"
							id={prefix + '-end'}
							type="date"
							min={start}
							bind:value={end}
							required
						/>
					</div>{/if}
			</div>{/if}
	</fieldset>
{/if}

<style>
	.policy-fields {
		margin-top: 1rem;
		padding-top: 1rem;
		border-top: var(--border-thin);
	}
	.visibility-options {
		display: flex;
		gap: 0.7rem;
		flex-wrap: wrap;
	}
	.visibility-options label {
		display: flex;
		gap: 0.4rem;
		align-items: center;
		font-size: 0.85rem;
		cursor: pointer;
		padding: 0.7rem;
		border: var(--border-thin);
		border-radius: 0.7rem;
	}
	.visibility-options label:has(input:checked) {
		background: var(--color-soft);
		border-color: var(--color-primary);
	}
	input[type='radio'] {
		accent-color: var(--color-primary);
	}
	.date-fields {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
		gap: 1rem;
	}
</style>
