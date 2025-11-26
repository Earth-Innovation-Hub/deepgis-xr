"""
World Sampler - Adaptive Geospatial Sampling System

This module provides a probabilistic framework for sampling locations on Earth (lat, lon, alt)
with an initial distribution that can be updated based on various rules and feedback.

Use cases:
    - Geospatial search and exploration
    - Active learning for Earth observation
    - Adaptive sampling strategies
    - Interest-based location discovery
"""

import numpy as np
from dataclasses import dataclass
from typing import List, Tuple, Optional, Callable, Dict
from scipy.stats import multivariate_normal
from scipy.spatial import KDTree


@dataclass
class SamplePoint:
    """Represents a sampled location on Earth"""
    lat: float  # Latitude in degrees [-90, 90]
    lon: float  # Longitude in degrees [-180, 180]
    alt: float  # Altitude in meters
    weight: float = 1.0  # Sampling weight/probability
    metadata: Dict = None  # Additional information
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
    
    def to_cartesian(self, radius: float = 6371000.0) -> np.ndarray:
        """Convert to 3D Cartesian coordinates for distance calculations"""
        lat_rad = np.radians(self.lat)
        lon_rad = np.radians(self.lon)
        r = radius + self.alt
        
        x = r * np.cos(lat_rad) * np.cos(lon_rad)
        y = r * np.cos(lat_rad) * np.sin(lon_rad)
        z = r * np.sin(lat_rad)
        
        return np.array([x, y, z])


class WorldSampler:
    """
    Adaptive world sampler with updatable distribution.
    
    Features:
        - Multiple initialization strategies (uniform, Gaussian mixture, custom)
        - Various update rules (Bayesian, reinforcement, user-defined)
        - Spatial correlation handling
        - Efficient sampling and querying
    """
    
    def __init__(
        self,
        num_points: int = 1000,
        lat_range: Tuple[float, float] = (-90, 90),
        lon_range: Tuple[float, float] = (-180, 180),
        alt_range: Tuple[float, float] = (0, 5000),
        initialization: str = 'uniform',
        seed: Optional[int] = None
    ):
        """
        Initialize the world sampler.
        
        Args:
            num_points: Number of sample points in the distribution
            lat_range: (min_lat, max_lat) in degrees
            lon_range: (min_lon, max_lon) in degrees
            alt_range: (min_alt, max_alt) in meters
            initialization: 'uniform', 'gaussian_mixture', or 'custom'
            seed: Random seed for reproducibility
        """
        self.num_points = num_points
        self.lat_range = lat_range
        self.lon_range = lon_range
        self.alt_range = alt_range
        self.rng = np.random.default_rng(seed)
        
        # Initialize sample points
        self.samples: List[SamplePoint] = []
        self._initialize_distribution(initialization)
        
        # Build spatial index for efficient querying
        self._build_spatial_index()
        
        # History tracking
        self.sample_history: List[SamplePoint] = []
        self.update_history: List[Dict] = []
    
    def _initialize_distribution(self, method: str = 'uniform'):
        """Initialize the sampling distribution"""
        if method == 'uniform':
            self._initialize_uniform()
        elif method == 'gaussian_mixture':
            self._initialize_gaussian_mixture()
        elif method == 'population_weighted':
            self._initialize_population_weighted()
        else:
            raise ValueError(f"Unknown initialization method: {method}")
    
    def _initialize_uniform(self):
        """Uniform distribution over the specified ranges"""
        lats = self.rng.uniform(self.lat_range[0], self.lat_range[1], self.num_points)
        lons = self.rng.uniform(self.lon_range[0], self.lon_range[1], self.num_points)
        alts = self.rng.uniform(self.alt_range[0], self.alt_range[1], self.num_points)
        
        self.samples = [
            SamplePoint(lat=lat, lon=lon, alt=alt, weight=1.0/self.num_points)
            for lat, lon, alt in zip(lats, lons, alts)
        ]
    
    def _initialize_gaussian_mixture(self, num_components: int = 5):
        """Gaussian mixture model initialization (e.g., around cities/landmarks)"""
        # Define some interesting locations (can be customized)
        interesting_locations = [
            (28.0, 86.9, 5000),      # Mount Everest
            (40.7, -74.0, 10),       # New York
            (51.5, -0.1, 10),        # London
            (-33.9, 18.4, 10),       # Cape Town
            (35.7, 139.7, 10),       # Tokyo
            (19.4, -99.1, 2250),     # Mexico City
            (-22.9, -43.2, 10),      # Rio de Janeiro
            (1.3, 103.8, 10),        # Singapore
        ]
        
        # Select random components
        num_components = min(num_components, len(interesting_locations))
        selected = self.rng.choice(len(interesting_locations), num_components, replace=False)
        centers = [interesting_locations[i] for i in selected]
        
        samples_per_component = self.num_points // num_components
        self.samples = []
        
        for center_lat, center_lon, center_alt in centers:
            # Generate samples around each center with some spread
            lats = self.rng.normal(center_lat, 10, samples_per_component)
            lons = self.rng.normal(center_lon, 10, samples_per_component)
            alts = self.rng.normal(center_alt, 100, samples_per_component)
            
            # Clip to valid ranges
            lats = np.clip(lats, self.lat_range[0], self.lat_range[1])
            lons = np.clip(lons, self.lon_range[0], self.lon_range[1])
            alts = np.clip(alts, self.alt_range[0], self.alt_range[1])
            
            for lat, lon, alt in zip(lats, lons, alts):
                self.samples.append(
                    SamplePoint(lat=lat, lon=lon, alt=alt, weight=1.0/self.num_points)
                )
    
    def _initialize_population_weighted(self):
        """Initialize based on approximate population density"""
        # Simplified population-weighted sampling
        # Higher density around equator and coastal regions
        lats = []
        lons = []
        alts = []
        
        for _ in range(self.num_points):
            # Bias towards lower latitudes (more population)
            lat = self.rng.beta(2, 2) * (self.lat_range[1] - self.lat_range[0]) + self.lat_range[0]
            # Uniform longitude
            lon = self.rng.uniform(self.lon_range[0], self.lon_range[1])
            # Most population at low altitude
            alt = self.rng.exponential(100)
            alt = min(alt, self.alt_range[1])
            
            lats.append(lat)
            lons.append(lon)
            alts.append(alt)
        
        self.samples = [
            SamplePoint(lat=lat, lon=lon, alt=alt, weight=1.0/self.num_points)
            for lat, lon, alt in zip(lats, lons, alts)
        ]
    
    def _build_spatial_index(self):
        """Build KD-tree for efficient spatial queries"""
        if len(self.samples) == 0:
            self.spatial_index = None
            return
        
        # Convert to Cartesian coordinates for better distance metrics
        points = np.array([s.to_cartesian() for s in self.samples])
        self.spatial_index = KDTree(points)
    
    def sample(self, n: int = 1, method: str = 'weighted') -> List[SamplePoint]:
        """
        Sample n points from the current distribution.
        
        Args:
            n: Number of points to sample
            method: 'weighted' (probability-based) or 'top_k' (highest weights)
        
        Returns:
            List of sampled points
        """
        if method == 'weighted':
            # Normalize weights
            weights = np.array([s.weight for s in self.samples])
            weights = weights / weights.sum()
            
            # Sample according to weights
            indices = self.rng.choice(len(self.samples), size=n, p=weights, replace=True)
            sampled_points = [self.samples[i] for i in indices]
            
        elif method == 'top_k':
            # Select top-k by weight
            sorted_samples = sorted(self.samples, key=lambda s: s.weight, reverse=True)
            sampled_points = sorted_samples[:n]
        
        else:
            raise ValueError(f"Unknown sampling method: {method}")
        
        # Track history
        self.sample_history.extend(sampled_points)
        
        return sampled_points
    
    def update_weights(
        self,
        rule: str,
        feedback_points: Optional[List[Tuple[float, float, float, float]]] = None,
        **kwargs
    ):
        """
        Update the sampling distribution based on feedback.
        
        Args:
            rule: Update rule to apply
                - 'reward': Increase weights near positive feedback locations
                - 'exploration': Increase weights in undersampled regions
                - 'concentration': Concentrate around high-value areas
                - 'custom': Use custom update function
            feedback_points: List of (lat, lon, alt, reward) tuples
            **kwargs: Additional parameters for the update rule
        """
        if rule == 'reward':
            self._update_reward(feedback_points, **kwargs)
        elif rule == 'exploration':
            self._update_exploration(**kwargs)
        elif rule == 'concentration':
            self._update_concentration(feedback_points, **kwargs)
        elif rule == 'custom':
            update_fn = kwargs.get('update_fn')
            if update_fn is None:
                raise ValueError("Custom rule requires 'update_fn' parameter")
            self._update_custom(update_fn, **kwargs)
        else:
            raise ValueError(f"Unknown update rule: {rule}")
        
        # Normalize weights
        self._normalize_weights()
        
        # Track update
        self.update_history.append({
            'rule': rule,
            'feedback_points': feedback_points,
            'kwargs': kwargs
        })
    
    def _update_reward(
        self,
        feedback_points: List[Tuple[float, float, float, float]],
        radius: float = 100000.0,  # meters
        learning_rate: float = 0.1
    ):
        """
        Reward-based update: Increase weights near positive feedback.
        
        Args:
            feedback_points: List of (lat, lon, alt, reward) tuples
            radius: Influence radius in meters
            learning_rate: How much to update (0-1)
        """
        if not feedback_points:
            return
        
        for sample in self.samples:
            sample_point = sample.to_cartesian()
            
            for lat, lon, alt, reward in feedback_points:
                feedback_point = SamplePoint(lat, lon, alt).to_cartesian()
                distance = np.linalg.norm(sample_point - feedback_point)
                
                # Gaussian influence based on distance
                influence = np.exp(-distance**2 / (2 * radius**2))
                
                # Update weight
                delta = learning_rate * reward * influence
                sample.weight *= (1 + delta)
    
    def _update_exploration(
        self,
        exploration_bonus: float = 0.5,
        min_distance: float = 50000.0  # meters
    ):
        """
        Exploration update: Increase weights in undersampled regions.
        """
        # Find regions far from recently sampled points
        if not self.sample_history:
            return
        
        recent_samples = self.sample_history[-min(10, len(self.sample_history)):]
        recent_points = np.array([s.to_cartesian() for s in recent_samples])
        
        for sample in self.samples:
            sample_point = sample.to_cartesian()
            
            # Distance to nearest recent sample
            distances = [np.linalg.norm(sample_point - rp) for rp in recent_points]
            min_dist = min(distances)
            
            # Bonus for being far from recent samples
            if min_dist > min_distance:
                bonus = exploration_bonus * (min_dist / min_distance)
                sample.weight *= (1 + bonus)
    
    def _update_concentration(
        self,
        feedback_points: List[Tuple[float, float, float, float]],
        concentration_factor: float = 2.0
    ):
        """
        Concentration update: Focus distribution around high-value areas.
        """
        if not feedback_points:
            return
        
        # Find top feedback points
        top_feedback = sorted(feedback_points, key=lambda x: x[3], reverse=True)[:5]
        
        for sample in self.samples:
            sample_point = sample.to_cartesian()
            
            # Calculate minimum distance to top feedback points
            min_distance = float('inf')
            for lat, lon, alt, reward in top_feedback:
                feedback_point = SamplePoint(lat, lon, alt).to_cartesian()
                distance = np.linalg.norm(sample_point - feedback_point)
                min_distance = min(min_distance, distance)
            
            # Increase weight inversely with distance
            if min_distance < 500000:  # Within 500km
                sample.weight *= concentration_factor * (1 - min_distance / 500000)
    
    def _update_custom(
        self,
        update_fn: Callable[[SamplePoint, Dict], float],
        **kwargs
    ):
        """Apply custom update function to each sample"""
        for sample in self.samples:
            weight_multiplier = update_fn(sample, kwargs)
            sample.weight *= weight_multiplier
    
    def _normalize_weights(self):
        """Normalize weights to sum to 1"""
        total_weight = sum(s.weight for s in self.samples)
        if total_weight > 0:
            for sample in self.samples:
                sample.weight /= total_weight
    
    def query_region(
        self,
        center_lat: float,
        center_lon: float,
        center_alt: float,
        radius: float = 100000.0
    ) -> List[SamplePoint]:
        """
        Query all samples within a radius of a center point.
        
        Args:
            center_lat, center_lon, center_alt: Center point
            radius: Query radius in meters
        
        Returns:
            List of samples within radius
        """
        if self.spatial_index is None:
            return []
        
        center_point = SamplePoint(center_lat, center_lon, center_alt).to_cartesian()
        
        # Query KD-tree
        indices = self.spatial_index.query_ball_point(center_point, radius)
        
        return [self.samples[i] for i in indices]
    
    def get_statistics(self) -> Dict:
        """Get statistics about the current distribution"""
        weights = np.array([s.weight for s in self.samples])
        lats = np.array([s.lat for s in self.samples])
        lons = np.array([s.lon for s in self.samples])
        alts = np.array([s.alt for s in self.samples])
        
        return {
            'num_samples': len(self.samples),
            'total_sampled': len(self.sample_history),
            'num_updates': len(self.update_history),
            'weight_stats': {
                'mean': float(weights.mean()),
                'std': float(weights.std()),
                'min': float(weights.min()),
                'max': float(weights.max()),
                'entropy': float(-np.sum(weights * np.log(weights + 1e-10)))
            },
            'spatial_coverage': {
                'lat_range': (float(lats.min()), float(lats.max())),
                'lon_range': (float(lons.min()), float(lons.max())),
                'alt_range': (float(alts.min()), float(alts.max())),
            }
        }
    
    def reset(self, keep_history: bool = False):
        """Reset the sampler to initial state"""
        if not keep_history:
            self.sample_history = []
            self.update_history = []
        
        # Re-initialize with same parameters
        self._initialize_distribution(method='uniform')
        self._build_spatial_index()


# Example usage and demonstration
if __name__ == '__main__':
    # Initialize sampler
    sampler = WorldSampler(
        num_points=1000,
        initialization='gaussian_mixture',
        seed=42
    )
    
    print("Initial statistics:")
    print(sampler.get_statistics())
    
    # Sample some points
    samples = sampler.sample(n=5, method='weighted')
    print(f"\nSampled {len(samples)} points:")
    for i, s in enumerate(samples, 1):
        print(f"  {i}. Lat: {s.lat:.2f}, Lon: {s.lon:.2f}, Alt: {s.alt:.0f}m, Weight: {s.weight:.6f}")
    
    # Simulate feedback (e.g., user found interesting locations)
    feedback = [
        (28.0, 86.9, 5000, 1.0),   # Mount Everest - high reward
        (40.7, -74.0, 10, 0.5),    # New York - medium reward
    ]
    
    print("\nApplying reward-based update...")
    sampler.update_weights('reward', feedback_points=feedback, learning_rate=0.2)
    
    # Sample again - should favor regions near feedback points
    samples = sampler.sample(n=5, method='weighted')
    print(f"\nSampled {len(samples)} points after update:")
    for i, s in enumerate(samples, 1):
        print(f"  {i}. Lat: {s.lat:.2f}, Lon: {s.lon:.2f}, Alt: {s.alt:.0f}m, Weight: {s.weight:.6f}")
    
    print("\nFinal statistics:")
    print(sampler.get_statistics())

