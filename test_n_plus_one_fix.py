"""
Test script to demonstrate N+1 query problem fix

This script shows the performance improvement from batch queries
"""
import asyncio
import time
from typing import List, Dict, Any


class MockDatabase:
    """Mock database to simulate N+1 query problem and solution"""
    
    def __init__(self):
        self.query_count = 0
        self.query_log = []
        
        # Mock data
        self.patients = [{"id": i, "name": f"Patient {i}"} for i in range(1, 51)]
        self.visits = {i: [{"id": j, "patient_id": i} for j in range(1, 6)] for i in range(1, 51)}
        self.reports = {i: [{"id": j, "patient_id": i} for j in range(1, 4)] for i in range(1, 51)}
    
    async def get_all_patients(self) -> List[Dict[str, Any]]:
        """Get all patients"""
        await asyncio.sleep(0.01)  # Simulate network delay
        self.query_count += 1
        self.query_log.append("SELECT * FROM patients")
        return self.patients
    
    async def get_visits_by_patient_id(self, patient_id: int) -> List[Dict[str, Any]]:
        """Get visits for one patient (N+1 pattern)"""
        await asyncio.sleep(0.01)  # Simulate network delay
        self.query_count += 1
        self.query_log.append(f"SELECT * FROM visits WHERE patient_id={patient_id}")
        return self.visits.get(patient_id, [])
    
    async def get_reports_by_patient_id(self, patient_id: int) -> List[Dict[str, Any]]:
        """Get reports for one patient (N+1 pattern)"""
        await asyncio.sleep(0.01)  # Simulate network delay
        self.query_count += 1
        self.query_log.append(f"SELECT * FROM reports WHERE patient_id={patient_id}")
        return self.reports.get(patient_id, [])
    
    async def get_visits_batch(self, patient_ids: List[int]) -> Dict[int, List[Dict[str, Any]]]:
        """Get visits for multiple patients in one query (OPTIMIZED)"""
        await asyncio.sleep(0.01)  # Simulate network delay
        self.query_count += 1
        self.query_log.append(f"SELECT * FROM visits WHERE patient_id IN ({','.join(map(str, patient_ids))})")
        return {pid: self.visits.get(pid, []) for pid in patient_ids}
    
    async def get_reports_batch(self, patient_ids: List[int]) -> Dict[int, List[Dict[str, Any]]]:
        """Get reports for multiple patients in one query (OPTIMIZED)"""
        await asyncio.sleep(0.01)  # Simulate network delay
        self.query_count += 1
        self.query_log.append(f"SELECT * FROM reports WHERE patient_id IN ({','.join(map(str, patient_ids))})")
        return {pid: self.reports.get(pid, []) for pid in patient_ids}


async def test_n_plus_one_problem():
    """Demonstrate the N+1 query problem"""
    print("=" * 70)
    print("TEST 1: N+1 Query Problem (BAD - Original Code)")
    print("=" * 70)
    
    db = MockDatabase()
    start_time = time.time()
    
    # Get all patients
    patients = await db.get_all_patients()
    
    # For each patient, get their visits and reports (N+1 problem!)
    results = []
    for patient in patients:
        patient_id = patient["id"]
        
        # Two queries per patient!
        visits = await db.get_visits_by_patient_id(patient_id)
        reports = await db.get_reports_by_patient_id(patient_id)
        
        results.append({
            "patient": patient,
            "visit_count": len(visits),
            "report_count": len(reports)
        })
    
    elapsed = (time.time() - start_time) * 1000
    
    print(f"\n📊 Results:")
    print(f"   Patients processed: {len(patients)}")
    print(f"   Total queries executed: {db.query_count}")
    print(f"   Time taken: {elapsed:.1f}ms")
    print(f"\n⚠️  Problem: 1 query for patients + {len(patients) * 2} queries for visits/reports")
    print(f"   = {db.query_count} total queries")
    
    return elapsed, db.query_count


async def test_batch_query_solution():
    """Demonstrate the batch query solution"""
    print("\n" + "=" * 70)
    print("TEST 2: Batch Query Solution (GOOD - Optimized Code)")
    print("=" * 70)
    
    db = MockDatabase()
    start_time = time.time()
    
    # Get all patients
    patients = await db.get_all_patients()
    patient_ids = [p["id"] for p in patients]
    
    # BATCH QUERY: Get all visits and reports in just 2 queries!
    visits_dict, reports_dict = await asyncio.gather(
        db.get_visits_batch(patient_ids),
        db.get_reports_batch(patient_ids)
    )
    
    # Process results with pre-fetched data
    results = []
    for patient in patients:
        patient_id = patient["id"]
        results.append({
            "patient": patient,
            "visit_count": len(visits_dict.get(patient_id, [])),
            "report_count": len(reports_dict.get(patient_id, []))
        })
    
    elapsed = (time.time() - start_time) * 1000
    
    print(f"\n📊 Results:")
    print(f"   Patients processed: {len(patients)}")
    print(f"   Total queries executed: {db.query_count}")
    print(f"   Time taken: {elapsed:.1f}ms")
    print(f"\n✅ Solution: 1 query for patients + 2 batch queries for visits/reports")
    print(f"   = {db.query_count} total queries")
    
    return elapsed, db.query_count


async def main():
    print("\n" + "🔍 " + "=" * 66)
    print("   N+1 Query Problem Demonstration")
    print("   " + "=" * 66)
    print("\n   Simulating cleanup of patient history for 50 patients...")
    print("   Each patient has ~5 visits and ~3 reports\n")
    
    # Run both tests
    old_time, old_queries = await test_n_plus_one_problem()
    new_time, new_queries = await test_batch_query_solution()
    
    # Show comparison
    print("\n" + "=" * 70)
    print("📈 PERFORMANCE COMPARISON")
    print("=" * 70)
    
    query_reduction = ((old_queries - new_queries) / old_queries) * 100
    time_reduction = ((old_time - new_time) / old_time) * 100
    speedup = old_time / new_time
    
    print(f"\n   Queries Reduced: {old_queries} → {new_queries} ({query_reduction:.1f}% reduction)")
    print(f"   Time Improved: {old_time:.1f}ms → {new_time:.1f}ms ({time_reduction:.1f}% faster)")
    print(f"   Speedup: {speedup:.1f}x faster")
    
    print(f"\n✨ Impact for Production:")
    print(f"   With 100 patients: {old_queries * 2} queries → {new_queries} queries")
    print(f"   With 500 patients: {old_queries * 10} queries → {new_queries} queries")
    print(f"   With 1000 patients: {old_queries * 20} queries → {new_queries} queries")
    
    print("\n" + "=" * 70)
    print("✅ N+1 Query Problem FIXED!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
