"""AE-K and VAE-C core (Maharjan, "Microservice Decomposition and Message Queues", Baylor M.S. thesis; code from
rokinmaharjan/benchmarking-monolith-to-microservices), ported cell-for-cell from machine-learning/ae.ipynb (AE-K: plain
autoencoder + hard KMeans) and machine-learning/code.ipynb (VAE-C: variational encoder + fuzzy c-means).

Shared graph/feature construction: entrypoint-reachability matrix E, co-entrypoint-path matrix C (DFS from each entrypoint),
X = D^-1/2 . A . D^-1/2 . [E | C], standardised. Documented deviation: the all-simple-paths DFS is exponential on branching or
cyclic graphs, so exploration is capped at `max_paths` per entrypoint (a WARNING is printed when it triggers).

TensorFlow/Keras and scikit-fuzzy are imported lazily so the numpy parts can be used and tested without them.
"""

import functools
import sys

import numpy as np
from scipy.linalg import fractional_matrix_power
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from dataset_graph import build_adjacency  # noqa: F401  (re-exported)


def build_graph(deps):
    not_keys = []
    for key, vals in deps.items():
        for cls in vals:
            if cls not in deps and cls not in not_keys:
                not_keys.append(cls)
    for key in not_keys:
        deps[key] = []

    node_to_class = {}
    class_to_node = {}
    for i, cls in enumerate(deps.keys()):
        node_to_class[i] = cls
        class_to_node[cls] = i

    n_nodes = len(deps)
    A = np.zeros((n_nodes, n_nodes))
    for key, lst in deps.items():
        for cls in lst:
            A[class_to_node[key], class_to_node[cls]] = 1
    return A, node_to_class, class_to_node

def dfs_for_E(node, visited, graph, E, ep_idx):
    if visited[node] == 1:
        return
    visited[node] = 1
    for i in range(graph.shape[1]):
        if graph[node, i] == 1:
            if E[i, ep_idx] == 0:
                E[i, ep_idx] = 1
            dfs_for_E(i, visited, graph, E, ep_idx)

def dfs_for_paths(node, graph, ep_idx, cur_path, paths, budget):
    if budget[0] <= 0:
        return
    if node in cur_path:
        paths[ep_idx].append(cur_path)
        budget[0] -= 1
        return
    tmp_path = cur_path + [node]
    if np.sum(graph[node]) == 0:
        paths[ep_idx].append(tmp_path)
        budget[0] -= 1
        return
    for i in range(graph.shape[1]):
        if budget[0] <= 0:
            return
        if graph[node, i] == 1:
            dfs_for_paths(i, graph, ep_idx, tmp_path, paths, budget)

def build_features(A, entrypoints, max_paths, info=None):
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 100000))
    n_nodes = A.shape[0]
    E = np.zeros((n_nodes, len(entrypoints)))
    for idx, ep in enumerate(entrypoints):
        visited = np.zeros(n_nodes)
        dfs_for_E(ep, visited, A, E, idx)

    paths = [[] for _ in range(len(entrypoints))]
    capped = False
    for idx, ep in enumerate(entrypoints):
        budget = [max_paths]
        dfs_for_paths(ep, A, idx, [], paths, budget)
        if budget[0] <= 0:
            capped = True
    if info is not None:
        info["capped"] = capped
    if capped:
        print("WARNING: co-entrypoint path exploration capped at %d paths/entrypoint "
              "(graph too large/cyclic for exhaustive enumeration) - degraded but not "
              "incorrect for the paths that were explored" % max_paths, file=sys.stderr)

    C = np.zeros((n_nodes, n_nodes))
    for ep_idx in range(len(entrypoints)):
        for path in paths[ep_idx]:
            path_set = list(dict.fromkeys(path))
            for i in path_set:
                for j in path_set:
                    if i != j:
                        C[i, j] += 1
                    else:
                        C[i, j] += 1

    for i in range(n_nodes):
        A[i, i] = 1
    D = np.zeros((n_nodes, n_nodes))
    for i in range(n_nodes):
        D[i, i] = np.sum(A[i])
    D_half_norm = fractional_matrix_power(D, -0.5)
    X = np.concatenate((E, C), axis=1)
    X = D_half_norm.dot(A).dot(D_half_norm).dot(X)
    return np.asarray(X, dtype=np.float64)

def elbow_k(sse_list, ks):
    x1, y1 = ks[0], sse_list[0]
    x2, y2 = ks[-1], sse_list[-1]
    best_k, best_dist = ks[0], -1
    for k, sse in zip(ks, sse_list):
        num = abs((y2 - y1) * k - (x2 - x1) * sse + x2 * y1 - y2 * x1)
        den = ((y2 - y1) ** 2 + (x2 - x1) ** 2) ** 0.5
        dist = num / den if den else 0
        if dist > best_dist:
            best_dist = dist
            best_k = k
    return best_k

def fuzzy_sse(Z, cntr, u):
    sse = 0.0
    for i in range(len(Z)):
        z_loc = np.asarray(Z[i])
        for j in range(cntr.shape[0]):
            c_loc = np.asarray(cntr[j])
            sse += u[j][i] * np.sum(np.square(z_loc - c_loc))
    return sse

@functools.lru_cache(maxsize=None)
def _models():
    """Keras model classes (built lazily so importing this module does not import TensorFlow)."""
    import tensorflow as tf
    from tensorflow import keras
    from tensorflow.keras import layers

    class AE(keras.Model):
        def __init__(self, encoder, decoder, A, **kwargs):
            super(AE, self).__init__(**kwargs)
            self.encoder = encoder
            self.decoder = decoder
            self.A = A
            self.total_loss_tracker = keras.metrics.Mean(name="total_loss")
            self.reconstruction_loss_tracker = keras.metrics.Mean(name="reconstruction_loss")
            self.architecture_loss_tracker = keras.metrics.Mean(name="architecture_loss")

        def call(self, inputs):
            x = self.encoder(inputs)
            return self.decoder(x)

        @property
        def metrics(self):
            return [self.total_loss_tracker, self.reconstruction_loss_tracker, self.architecture_loss_tracker]

        def train_step(self, data):
            with tf.GradientTape() as tape:
                z = self.encoder(data)
                reconstruction = self.decoder(z)
                reconstruction_loss = tf.reduce_mean(tf.reduce_sum(tf.square(data - reconstruction), axis=(1,)))
                architecture_loss = tf.reduce_mean(tf.square(self.A - tf.matmul(z, z, transpose_b=True)))
                total_loss = reconstruction_loss + architecture_loss
            grads = tape.gradient(total_loss, self.trainable_weights)
            self.optimizer.apply_gradients(zip(grads, self.trainable_weights))
            self.total_loss_tracker.update_state(total_loss)
            self.reconstruction_loss_tracker.update_state(reconstruction_loss)
            self.architecture_loss_tracker.update_state(architecture_loss)
            return {
                "loss": self.total_loss_tracker.result(),
                "reconstruction_loss": self.reconstruction_loss_tracker.result(),
                "architecture_loss": self.architecture_loss_tracker.result(),
            }

    class Sampling(layers.Layer):
        """Reparameterization trick: samples z from (z_mean, z_log_var)."""

        def call(self, inputs):
            z_mean, z_log_var = inputs
            batch = tf.shape(z_mean)[0]
            dim = tf.shape(z_mean)[1]
            epsilon = tf.keras.backend.random_normal(shape=(batch, dim))
            return z_mean + tf.exp(0.5 * z_log_var) * epsilon

    class VAE(keras.Model):
        def __init__(self, encoder, decoder, A, **kwargs):
            super(VAE, self).__init__(**kwargs)
            self.encoder = encoder
            self.decoder = decoder
            self.A = A
            self.total_loss_tracker = keras.metrics.Mean(name="total_loss")
            self.reconstruction_loss_tracker = keras.metrics.Mean(name="reconstruction_loss")
            self.kl_loss_tracker = keras.metrics.Mean(name="kl_loss")
            self.architecture_loss_tracker = keras.metrics.Mean(name="architecture_loss")

        def call(self, inputs):
            mean, log_var, x = self.encoder(inputs)
            return self.decoder(x)

        @property
        def metrics(self):
            return [self.total_loss_tracker, self.reconstruction_loss_tracker,
                    self.kl_loss_tracker, self.architecture_loss_tracker]

        def train_step(self, data):
            with tf.GradientTape() as tape:
                z_mean, z_log_var, z = self.encoder(data)
                reconstruction = self.decoder(z)
                reconstruction_loss = tf.reduce_mean(tf.reduce_sum(tf.square(data - reconstruction), axis=(1,)))
                kl_loss = -0.5 * (1 + z_log_var - tf.square(z_mean) - tf.exp(z_log_var))
                kl_loss = tf.reduce_mean(tf.reduce_sum(kl_loss, axis=1))
                architecture_loss = tf.reduce_mean(tf.square(self.A - tf.matmul(z, z, transpose_b=True)))
                total_loss = reconstruction_loss + kl_loss + architecture_loss
            grads = tape.gradient(total_loss, self.trainable_weights)
            self.optimizer.apply_gradients(zip(grads, self.trainable_weights))
            self.total_loss_tracker.update_state(total_loss)
            self.reconstruction_loss_tracker.update_state(reconstruction_loss)
            self.kl_loss_tracker.update_state(kl_loss)
            self.architecture_loss_tracker.update_state(architecture_loss)
            return {
                "loss": self.total_loss_tracker.result(),
                "reconstruction_loss": self.reconstruction_loss_tracker.result(),
                "kl_loss": self.kl_loss_tracker.result(),
                "architecture_loss": self.architecture_loss_tracker.result(),
            }

    return AE, VAE, Sampling


def _encoder_decoder_layers(n_features, n_embeddings, variational):
    from tensorflow.keras import Input, Model
    from tensorflow.keras.layers import Dense

    AE, VAE, Sampling = _models()
    input_encoder = Input(shape=(n_features,))
    n_neurons = n_features // 2
    x = Dense(n_neurons, activation="tanh")(input_encoder)
    n_neurons = n_neurons // 2
    while n_neurons >= n_embeddings * 2:
        x = Dense(n_neurons, activation="tanh")(x)
        n_neurons = n_neurons // 2
    if variational:
        z_mean = Dense(n_embeddings, name="z_mean")(x)
        z_log_var = Dense(n_embeddings, name="z_log_var")(x)
        z = Sampling()([z_mean, z_log_var])
        encoder = Model(input_encoder, [z_mean, z_log_var, z], name="encoder")
    else:
        z = Dense(n_embeddings, name="z")(x)
        encoder = Model(input_encoder, z, name="encoder")

    input_decoder = Input(shape=(n_embeddings,))
    n_neurons = n_embeddings * 2
    x = Dense(n_neurons, activation="tanh")(input_decoder)
    n_neurons = n_neurons * 2
    while n_neurons <= n_features // 2:
        x = Dense(n_neurons, activation="tanh")(x)
        n_neurons = n_neurons * 2
    recon = Dense(n_features)(x)
    decoder = Model(input_decoder, recon, name="decoder")
    return encoder, decoder


def train_ae(X, A, n_embeddings=2, n_epochs=8000, lr=0.001):
    import tensorflow as tf
    from tensorflow.keras.optimizers import Adam

    AE, _, _ = _models()
    encoder, decoder = _encoder_decoder_layers(X.shape[1], n_embeddings, variational=False)
    ae = AE(encoder, decoder, tf.constant(A, dtype=tf.float32))
    ae.compile(optimizer=Adam(lr))
    ae.built = True
    ae.fit(X, epochs=n_epochs, batch_size=X.shape[0], verbose=0)
    return ae.encoder(X).numpy()


def train_vae(X, A, n_embeddings=2, n_epochs=8000, lr=0.001):
    import tensorflow as tf
    from tensorflow.keras.optimizers import Adam

    _, VAE, _ = _models()
    encoder, decoder = _encoder_decoder_layers(X.shape[1], n_embeddings, variational=True)
    vae = VAE(encoder, decoder, tf.constant(A, dtype=tf.float32))
    vae.compile(optimizer=Adam(lr))
    vae.built = True
    vae.fit(X, epochs=n_epochs, batch_size=X.shape[0], verbose=0)
    _, _, z_final = vae.encoder(X)
    return z_final.numpy()


def _seed(seed):
    import tensorflow as tf

    tf.keras.utils.set_random_seed(seed)


def _features(adj, entrypoints, max_paths, info):
    A, node_to_class, class_to_node = build_graph({k: list(v) for k, v in adj.items()})
    eps = [class_to_node[e] for e in entrypoints if e in class_to_node]
    if not eps:
        raise ValueError("no entrypoints resolved against the dependency graph")
    X = build_features(A.copy(), eps, max_paths, info)
    X = np.nan_to_num(StandardScaler().fit_transform(X))
    return A, X, node_to_class


def run_ae_k(adj, entrypoints, seed, max_paths=20000, max_k=20, n_epochs=8000, info=None):
    """AE-K: autoencoder embeddings, KMeans swept k=2..max_k, k by SSE elbow. Returns {class: cluster}."""
    info = {} if info is None else info
    A, X, node_to_class = _features(adj, entrypoints, max_paths, info)
    _seed(seed)
    Z = train_ae(X, A, n_epochs=n_epochs)

    ks = list(range(2, min(max_k, A.shape[0] - 1) + 1))
    sse_list, labels_by_k = [], {}
    for k in ks:
        km = KMeans(n_clusters=k, random_state=0, n_init=10).fit(Z)
        sse_list.append(sum(np.sum((Z[i] - km.cluster_centers_[km.labels_[i]]) ** 2) for i in range(len(Z))))
        labels_by_k[k] = km.labels_
    best_k = elbow_k(sse_list, ks)
    info["k"] = best_k
    return {node_to_class[i]: int(c) for i, c in enumerate(labels_by_k[best_k])}


def run_vae_c(adj, entrypoints, seed, k=None, max_paths=20000, max_k=20, n_epochs=8000, info=None):
    """VAE-C: variational embeddings, fuzzy c-means (m=2), hardened by argmax; fixed k, or SSE elbow if k is None."""
    import skfuzzy as fuzz

    info = {} if info is None else info
    A, X, node_to_class = _features(adj, entrypoints, max_paths, info)
    _seed(seed)
    Z = train_vae(X, A, n_epochs=n_epochs)

    if k is not None:
        best_k = k
        cntr, u, *_ = fuzz.cluster.cmeans(Z.T, best_k, 2, error=0.005, maxiter=1000, init=None)
    else:
        ks = list(range(2, min(max_k, A.shape[0] - 1) + 1))
        sse_list, u_by_k = [], {}
        for kk in ks:
            cntr, u, *_ = fuzz.cluster.cmeans(Z.T, kk, 2, error=0.005, maxiter=1000, init=None)
            sse_list.append(fuzzy_sse(Z, cntr, u))
            u_by_k[kk] = u
        best_k = elbow_k(sse_list, ks)
        u = u_by_k[best_k]
    info["k"] = best_k
    labels = np.argmax(u.T, axis=1)
    return {node_to_class[i]: int(c) for i, c in enumerate(labels)}
