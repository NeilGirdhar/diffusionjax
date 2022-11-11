import jax
import optax
import jax.numpy as jnp
import flax.linen as nn
import jax.random as random
from jax import vmap, jit
from sgm.utils import (
    matrix_inverse, matrix_solve,
    optimizer)
from functools import partial
from jax.experimental.host_callback import id_print
from sgm.utils import update_step as nonlinear_update_step


class Linear(nn.Module):
    """A simple model with multiple fully connected layers and some fourier features for the time variable."""

    @nn.compact
    def __call__(self, x, t):
        batch_size = x.shape[0]
        N = jnp.shape(x)[1]
        in_size = (N + 1) * N
        n_hidden = 256
        h = jnp.array([t - 0.5, jnp.cos(2*jnp.pi*t)]).T
        h = nn.Dense(n_hidden)(h)
        h = nn.relu(h)
        h = nn.Dense(n_hidden)(h)
        h = nn.relu(h)
        h = nn.Dense(n_hidden)(h)
        h = nn.relu(h)
        h = nn.Dense(in_size)(h)
        h = jnp.reshape(h, (batch_size, N + 1, N))  # (batch_size, N + 1, N)
        h = jnp.einsum('ijk, ij -> ik', h, jnp.hstack((jnp.ones((batch_size, 1)), x)))
        return h  # (n_batch,)

    def evaluate(self, params, x_t, times):
        return model.apply(params, times, x_t)  #  (n_batch, N, N+1) which is quite memory intense


class Matrix(nn.Module):
    """A simple model with multiple fully connected layers and some fourier features for the time variable."""

    @nn.compact
    def __call__(self, t, N):
        batch_size = jnp.size(t)
        in_size = (N + 1) * N
        n_hidden = 256
        # h = jnp.concatenate([t - 0.5, jnp.cos(2*jnp.pi*t)], axis=1)  # (n_batch, 2)
        h = jnp.array([t - 0.5, jnp.cos(2*jnp.pi*t)]).T  # (n_batch, 2)
        h = nn.Dense(n_hidden)(h)
        h = nn.relu(h)
        h = nn.Dense(n_hidden)(h)
        h = nn.relu(h)
        h = nn.Dense(n_hidden)(h)
        h = nn.relu(h)
        h = nn.Dense(in_size)(h)
        h = jnp.reshape(h, (batch_size, N + 1, N))  # (batch_size, N + 1, N)
        return h

    def evaluate(self, params, x_t, times):
        h = self.apply(params, times, jnp.shape(x_t)[1])  #  (n_batch, N, N+1) which is quite memory intense
        return jnp.einsum('ijk, ij -> ik', h, jnp.hstack((jnp.ones((jnp.shape(x_t)[0], 1)), x_t)))

    def evaluate_eig(self, params, x_t, times):
        h = model.apply(params, times, jnp.shape(x_t)[0])  #  (n_batch, N, N+1) which is quite memory intense
        h = jnp.einsum('ijk, ij -> ik', h, jnp.hstack((jnp.ones((n_batch, 1)), x_t)))
        H = h[0, :, 1]
        mu = h[0, :, 1:]
        x = jnp.einsum('ijk, ij -> ik', h, jnp.hstack((jnp.ones((batch_size, 1)), x)))
        return  jnp.linalg.eig(h[0, 1:, :])


class Cholesky(nn.Module):
    """A simple model with multiple fully connected layers and some fourier features for the time variable."""

    @nn.compact
    def __call__(self, t, N):
        batch_size = jnp.size(t)
        in_size = (N + 1) * N
        n_hidden = 256
        # h = jnp.concatenate([t - 0.5, jnp.cos(2*jnp.pi*t)], axis=1)  # (n_batch, 2)
        h = jnp.array([t - 0.5, jnp.cos(2*jnp.pi*t)]).T  # (n_batch, 2)
        h = nn.Dense(n_hidden)(h)
        h = nn.relu(h)
        h = nn.Dense(n_hidden)(h)
        h = nn.relu(h)
        h = nn.Dense(n_hidden)(h)
        h = nn.relu(h)
        h = nn.Dense(in_size)(h)
        h = jnp.reshape(h, (batch_size, N + 1, N))  # (batch_size, N + 1, N)
        return h

    def evaluate(self, params, x_t, times):
        h = self.apply(params, times, jnp.shape(x_t)[0])  #  (n_batch, N, N+1) which is quite memory intense
        L = h[:, :-1, :]  # (n_batch, N, N)
        mu = h[:, -1, :]  # (n_batch, N)
        h = jnp.einsum('ijk, ij -> ik', L, x_t)  # (n_batch, N)
        h = jnp.einsum('ijk, ik -> ij', L, h)  # (n_batch, N)
        return (h + mu)  # (n_batch, N)  # L @ L.T @ x_t + mu

    def evaluate_eig(self, params, x_t, times):
        h = self.apply(params, times, jnp.shape(x_t)[0])  #  (n_batch, N, N+1) which is quite memory intense
        h = jnp.einsum('ijk, ij -> ik', h, jnp.hstack((jnp.ones((n_batch, 1)), x_t)))
        L = h[:, :-1, :]  # (n_batch, N, N)
        H = L.T @ L
        return  jnp.linalg.eig(H)


def train_linear_nn(rng, mf, batch_size, score_model, N_epochs):
    rng, step_rng = random.split(rng)
    train_size = mf.shape[0]
    N = mf.shape[1]
    batch_size = 5
    batch_size = min(train_size, batch_size)
    x = jnp.zeros(N*batch_size).reshape((batch_size, N))
    time = jnp.ones((batch_size, 1))
    print(jnp.shape(x))
    print(jnp.shape(time))
    params = score_model.init(step_rng, x, time)
    opt_state = optimizer.init(params)
    steps_per_epoch = train_size // batch_size
    for k in range(N_epochs):
        rng, step_rng = random.split(rng)
        perms = jax.random.permutation(step_rng, train_size)
        perms = perms[:steps_per_epoch * batch_size]  # skip incomplete batch
        perms = perms.reshape((steps_per_epoch, batch_size))
        losses = []
        for perm in perms:
            batch = mf[perm, :]
            rng, step_rng = random.split(rng)
            loss, params, opt_state = nonlinear_update_step(params, step_rng, batch, opt_state, score_model, linear_loss_fn)
            losses.append(loss)
        mean_loss = jnp.mean(jnp.array(losses))
        if k % 1 == 0:
            print("Epoch %d \t, Loss %f " % (k, mean_loss))
    return score_model, params


@partial(jit, static_argnums=[0, 1, 2, 6, 7, 8])
def update_step(n_batch, m_0, C_0, params, rng, opt_state, model, loss_fn, has_aux=False):
    """
    params: the current weights of the model
    rng: random number generator from jax
    batch: a batch of samples from the training data, representing samples from \mu_text{data}, shape (J, N)
    opt_state: the internal state of the optimizer
    model: the  function

    takes the gradient of the loss function and updates the model weights (params) using it. Returns
    the value of the loss function (for metrics), the new params and the new optimizer state
    """
    # TODO: There isn't a more efficient place to factorize jax value_and_grad?
    # Is this linear loss function
    val, grads = jax.value_and_grad(loss_fn, has_aux=has_aux)(params, model, rng, n_batch, m_0, C_0)
    updates, opt_state = optimizer.update(grads, opt_state)
    params = optax.apply_updates(params, updates)
    return val, params, opt_state


def retrain_nn(
        n_batch, m_0, C_0, N_epochs, rng,
        score_model, params, opt_state, loss_fn,
        decomposition=False):
    if decomposition:
        L = 2
    else:
        L = 1
    steps_per_epoch = 1
    print("N_epochs = {}, steps_per_epoch = {}".format(N_epochs, steps_per_epoch))
    mean_losses = jnp.zeros((N_epochs, L))
    for i in range(N_epochs):
        rng, step_rng = random.split(rng)
        loss, params, opt_state = update_step(
            n_batch, m_0, C_0, params, step_rng,
            opt_state, score_model, loss_fn,
            has_aux=decomposition)
        if decomposition:
            loss = loss[1]
        mean_losses = mean_losses.at[i].set(loss)
        if i % 1 == 0:
            if L==1: print(
                "Epoch {:d}, Loss {:.2f} ".format(i, loss))
            if L==2: print(
                "Tangent loss {:.2f}, perpendicular loss {:.2f}".format(loss[0], loss[1]))
    return score_model, params, opt_state, mean_losses


# TODO: what are these for?
def sqrt_linear_trained_score(score_model, params, t, N, x):
    v = var(t)  # (n_batch, N)
    stds = jnp.sqrt(v)
    s = score_model.apply(params, t, N)
    L = s[:, :-1, :]  # (n_batch, N, N)
    mu = s[:, -1, :]  # (n_batch, N)
    s = jnp.einsum('ijk, ij -> ik', L, x)  # (n_batch, N)
    s = jnp.einsum('ijk, ik -> ij', L, s)  # (n_batch, N)
    return (s + mu) / stds  # (n_batch, N)  # L @ L.T @ x_t + mu


def linear_trained_score(score_model, params, t, N, x, n_samples):
    v = var(t)  # (n_batch, N)
    stds = jnp.sqrt(v)
    s = score_model.apply(params, t, N)  # (n_samples, N + 1, N)
    return jnp.einsum('ijk, ij -> ik', s, jnp.hstack((jnp.ones((n_samples, 1)), x))) / stds
