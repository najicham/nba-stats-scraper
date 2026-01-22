# Proxy Provider Evaluation

**Last Updated:** 2026-01-22

## Current Provider

### ProxyFuel
- **Plan:** Rotating Pro 1M
- **Price:** ~$X/month for 1M requests
- **Type:** Datacenter rotating proxies
- **Issue:** Target sites (BettingPros, NBA.com, OddsAPI) are blocking datacenter IPs

## Evaluation Criteria

| Criteria | Weight | Description |
|----------|--------|-------------|
| Residential IPs | High | Harder to detect/block than datacenter |
| Success Rate | High | % of requests that succeed |
| Speed | Medium | Response time latency |
| Price | Medium | Cost per GB or per request |
| Sports/Betting Support | Medium | Experience with these targets |
| Rotation Options | Low | Sticky sessions vs per-request |

## Provider Comparison

### Tier 1: Enterprise (Best Success Rates)

#### Bright Data
- **Price:** ~$6/GB (residential)
- **Pool Size:** 72M+ residential IPs
- **Pros:**
  - Highest success rates
  - Best geo-targeting
  - Compliance tools
  - Dedicated support
- **Cons:**
  - Most expensive
  - Complex pricing
- **Best For:** Mission-critical scraping

#### Oxylabs
- **Price:** ~$8/GB (residential)
- **Pool Size:** 100M+ IPs
- **Pros:**
  - 99.95% success rate (claimed)
  - Fastest response times (0.41s avg)
  - Good documentation
- **Cons:**
  - Premium pricing
- **Best For:** High-reliability requirements

### Tier 2: Best Value (Recommended)

#### Decodo (formerly Smartproxy) ⭐ RECOMMENDED
- **Price:** ~$4/GB (residential)
- **Pool Size:** 55M+ residential IPs
- **Pros:**
  - Best price/performance ratio
  - Sub-2.5ms response times
  - Easy API integration
  - Good for sports data
- **Cons:**
  - Smaller pool than enterprise options
- **Best For:** Our use case - good balance of reliability and cost
- **Website:** https://decodo.com

### Tier 3: Budget Options

#### IPRoyal
- **Price:** ~$7/GB
- **Pool Size:** 32M+ IPs
- **Pros:**
  - Flexible rotation (up to 24h sticky)
  - Credit-based purchasing
  - No minimum commitment
- **Cons:**
  - Lower success rates
- **Best For:** Testing, low-volume scraping

#### Webshare
- **Price:** ~$2-3/GB
- **Pool Size:** 30M+ IPs
- **Pros:**
  - Cheapest option
  - Good latency
- **Cons:**
  - Lower success rates on protected sites
- **Best For:** High-volume, less-protected targets

## Recommendation

**Primary: Decodo/Smartproxy**
- Reason: Best value for sports/betting data scraping
- Expected cost: ~$100-200/month based on our volume
- Trial available to test before committing

**Backup: Bright Data**
- If Decodo doesn't work for specific targets
- Higher cost but highest reliability

## Migration Considerations

1. **Test Before Switching**
   - Get trial from new provider
   - Test against all target sites
   - Verify success rates

2. **Gradual Rollout**
   - Start with one scraper type
   - Monitor success rates
   - Expand if successful

3. **Keep Fallback**
   - Don't cancel old provider immediately
   - Have ability to switch back quickly

## Cost Estimation

Based on our current usage:
- ~10,000-50,000 requests/day for betting data
- ~5,000 requests/day for NBA stats
- Estimated bandwidth: 50-100 GB/month

| Provider | Estimated Monthly Cost |
|----------|----------------------|
| ProxyFuel (current) | ~$50 (request-based) |
| Decodo | ~$200-400 (GB-based) |
| Bright Data | ~$300-600 (GB-based) |

## References

- [Proxyway Rankings 2026](https://proxyway.com/best/residential-proxies)
- [ZenRows Proxy Guide](https://www.zenrows.com/blog/web-scraping-proxy)
- [AIMutiple Comparison](https://research.aimultiple.com/residential-proxy-providers/)
