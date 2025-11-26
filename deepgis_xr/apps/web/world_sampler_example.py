"""
World Sampler Usage Examples

Demonstrates various use cases for the adaptive world sampling system.
"""

from world_sampler import WorldSampler, SamplePoint
import json


def example_1_basic_sampling():
    """Basic sampling with uniform distribution"""
    print("=" * 60)
    print("Example 1: Basic Uniform Sampling")
    print("=" * 60)
    
    sampler = WorldSampler(
        num_points=500,
        initialization='uniform',
        seed=42
    )
    
    # Sample 10 locations
    samples = sampler.sample(n=10)
    
    print("\nSampled 10 random locations:")
    for i, s in enumerate(samples, 1):
        print(f"{i:2d}. Lat: {s.lat:7.3f}°, Lon: {s.lon:8.3f}°, Alt: {s.alt:6.1f}m")
    
    return sampler


def example_2_interest_areas():
    """Initialize around areas of interest (cities, landmarks)"""
    print("\n" + "=" * 60)
    print("Example 2: Sampling Around Points of Interest")
    print("=" * 60)
    
    sampler = WorldSampler(
        num_points=500,
        initialization='gaussian_mixture',
        seed=42
    )
    
    samples = sampler.sample(n=10)
    
    print("\nSampled 10 locations (biased towards cities/landmarks):")
    for i, s in enumerate(samples, 1):
        print(f"{i:2d}. Lat: {s.lat:7.3f}°, Lon: {s.lon:8.3f}°, Alt: {s.alt:6.1f}m")
    
    return sampler


def example_3_reward_based_learning():
    """Update distribution based on user feedback"""
    print("\n" + "=" * 60)
    print("Example 3: Reward-Based Learning")
    print("=" * 60)
    
    sampler = WorldSampler(
        num_points=1000,
        initialization='uniform',
        seed=42
    )
    
    print("\nInitial sampling (uniform):")
    initial_samples = sampler.sample(n=5)
    for i, s in enumerate(initial_samples, 1):
        print(f"{i}. Lat: {s.lat:7.3f}°, Lon: {s.lon:8.3f}°")
    
    # Simulate user finding interesting locations
    print("\nUser provides feedback on interesting locations:")
    feedback = [
        (28.0, 86.9, 8848, 1.0),    # Mount Everest - very interesting
        (-33.9, 18.4, 10, 0.8),     # Table Mountain - interesting
        (64.0, -16.0, 10, 0.6),     # Iceland - somewhat interesting
    ]
    
    for lat, lon, alt, reward in feedback:
        print(f"  • ({lat:.1f}°, {lon:.1f}°, {alt:.0f}m) - reward: {reward}")
    
    # Update distribution
    sampler.update_weights('reward', feedback_points=feedback, learning_rate=0.3)
    
    print("\nAfter learning (should sample near feedback locations):")
    updated_samples = sampler.sample(n=10)
    for i, s in enumerate(updated_samples, 1):
        print(f"{i:2d}. Lat: {s.lat:7.3f}°, Lon: {s.lon:8.3f}°")
    
    stats = sampler.get_statistics()
    print(f"\nDistribution entropy: {stats['weight_stats']['entropy']:.4f}")
    
    return sampler


def example_4_exploration_strategy():
    """Encourage exploration of undersampled regions"""
    print("\n" + "=" * 60)
    print("Example 4: Exploration Strategy")
    print("=" * 60)
    
    sampler = WorldSampler(
        num_points=1000,
        initialization='uniform',
        seed=42
    )
    
    # Sample some locations (simulating initial exploration)
    print("\nInitial exploration:")
    for i in range(3):
        samples = sampler.sample(n=3)
        print(f"  Round {i+1}: {len(samples)} samples taken")
    
    # Apply exploration update to encourage sampling in new areas
    sampler.update_weights('exploration', exploration_bonus=0.5)
    
    print("\nAfter exploration update (should sample in less-visited areas):")
    new_samples = sampler.sample(n=5)
    for i, s in enumerate(new_samples, 1):
        print(f"{i}. Lat: {s.lat:7.3f}°, Lon: {s.lon:8.3f}°")
    
    return sampler


def example_5_concentration():
    """Concentrate sampling around high-value areas"""
    print("\n" + "=" * 60)
    print("Example 5: Concentration Around High-Value Areas")
    print("=" * 60)
    
    sampler = WorldSampler(
        num_points=1000,
        initialization='uniform',
        seed=42
    )
    
    # Identify high-value locations
    high_value_locations = [
        (40.7, -74.0, 10, 1.0),     # New York City
        (51.5, -0.1, 10, 0.9),      # London
        (35.7, 139.7, 10, 0.95),    # Tokyo
    ]
    
    print("\nHigh-value locations identified:")
    for lat, lon, alt, value in high_value_locations:
        print(f"  • ({lat:.1f}°, {lon:.1f}°) - value: {value}")
    
    sampler.update_weights(
        'concentration',
        feedback_points=high_value_locations,
        concentration_factor=3.0
    )
    
    print("\nAfter concentration (most samples near high-value areas):")
    samples = sampler.sample(n=10)
    for i, s in enumerate(samples, 1):
        print(f"{i:2d}. Lat: {s.lat:7.3f}°, Lon: {s.lon:8.3f}°")
    
    return sampler


def example_6_custom_update_rule():
    """Define and apply custom update logic"""
    print("\n" + "=" * 60)
    print("Example 6: Custom Update Rule")
    print("=" * 60)
    
    sampler = WorldSampler(
        num_points=1000,
        initialization='uniform',
        seed=42
    )
    
    # Custom rule: Favor locations at high altitude and in Northern hemisphere
    def altitude_and_latitude_bonus(sample: SamplePoint, params: dict) -> float:
        """Bonus for high altitude and northern latitude"""
        alt_bonus = 1.0 + (sample.alt / 5000.0) * 0.5  # Up to 50% bonus for 5000m
        lat_bonus = 1.0 + (max(0, sample.lat) / 90.0) * 0.5  # Up to 50% for North pole
        return alt_bonus * lat_bonus
    
    print("\nApplying custom rule: favor high altitude + northern hemisphere")
    sampler.update_weights('custom', update_fn=altitude_and_latitude_bonus)
    
    samples = sampler.sample(n=10)
    print("\nSampled locations:")
    for i, s in enumerate(samples, 1):
        print(f"{i:2d}. Lat: {s.lat:7.3f}°, Lon: {s.lon:8.3f}°, Alt: {s.alt:6.1f}m")
    
    avg_lat = sum(s.lat for s in samples) / len(samples)
    avg_alt = sum(s.alt for s in samples) / len(samples)
    print(f"\nAverage: Lat = {avg_lat:.1f}°, Alt = {avg_alt:.1f}m")
    
    return sampler


def example_7_spatial_query():
    """Query samples in a specific region"""
    print("\n" + "=" * 60)
    print("Example 7: Spatial Query")
    print("=" * 60)
    
    sampler = WorldSampler(
        num_points=1000,
        initialization='gaussian_mixture',
        seed=42
    )
    
    # Query region around Mount Everest
    query_lat, query_lon, query_alt = 28.0, 86.9, 8848
    radius = 200000  # 200 km
    
    print(f"\nQuerying region around ({query_lat}°, {query_lon}°)")
    print(f"Radius: {radius/1000:.0f} km")
    
    nearby_samples = sampler.query_region(
        query_lat, query_lon, query_alt, radius
    )
    
    print(f"\nFound {len(nearby_samples)} samples in region:")
    for i, s in enumerate(nearby_samples[:10], 1):  # Show first 10
        print(f"{i:2d}. Lat: {s.lat:7.3f}°, Lon: {s.lon:8.3f}°, Alt: {s.alt:6.1f}m")
    
    if len(nearby_samples) > 10:
        print(f"  ... and {len(nearby_samples) - 10} more")
    
    return sampler


def example_8_export_for_cesium():
    """Export samples in format suitable for Cesium visualization"""
    print("\n" + "=" * 60)
    print("Example 8: Export for Cesium")
    print("=" * 60)
    
    sampler = WorldSampler(
        num_points=100,
        initialization='gaussian_mixture',
        seed=42
    )
    
    samples = sampler.sample(n=20, method='weighted')
    
    # Convert to GeoJSON for Cesium
    features = []
    for i, s in enumerate(samples):
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [s.lon, s.lat, s.alt]
            },
            "properties": {
                "id": i,
                "weight": s.weight,
                "description": f"Sample point {i+1}"
            }
        }
        features.append(feature)
    
    geojson = {
        "type": "FeatureCollection",
        "features": features
    }
    
    print("\nGenerated GeoJSON with 20 sample points")
    print(f"First sample: {json.dumps(features[0], indent=2)}")
    print("\nThis can be loaded directly into Cesium viewer!")
    
    return geojson


def run_all_examples():
    """Run all examples in sequence"""
    print("\n" + "=" * 60)
    print("WORLD SAMPLER - COMPLETE EXAMPLES")
    print("=" * 60)
    
    examples = [
        example_1_basic_sampling,
        example_2_interest_areas,
        example_3_reward_based_learning,
        example_4_exploration_strategy,
        example_5_concentration,
        example_6_custom_update_rule,
        example_7_spatial_query,
        example_8_export_for_cesium,
    ]
    
    results = []
    for example_fn in examples:
        result = example_fn()
        results.append(result)
        input("\nPress Enter to continue to next example...")
    
    print("\n" + "=" * 60)
    print("All examples completed!")
    print("=" * 60)
    
    return results


if __name__ == '__main__':
    # Run all examples
    run_all_examples()

