<p id="password-rules" class="help mb-4">
	10 à 128 caractères : au moins une minuscule, une majuscule, un chiffre et un signe de ponctuation
	ASCII. Sans espace ni accent.
</p>
<div class="field">
	<label class="label" for="password">Nouveau mot de passe</label>
	<div class="control">
		<input
			class="input"
			id="password"
			name="password"
			type="password"
			autocomplete="new-password"
			minlength="10"
			maxlength="128"
			aria-describedby="password-rules"
			required
		/>
	</div>
</div>
<div class="field">
	<label class="label" for="confirmation">Confirmer le mot de passe</label>
	<div class="control">
		<input
			class="input"
			id="confirmation"
			name="confirmation"
			type="password"
			autocomplete="new-password"
			minlength="10"
			maxlength="128"
			required
		/>
	</div>
</div>
