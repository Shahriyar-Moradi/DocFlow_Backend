"""
Quick test to verify MockFirestoreService flow operations work correctly
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

from services.mocks import MockFirestoreService

def test_mock_flow_operations():
    """Test all flow operations in MockFirestoreService"""
    print("Testing MockFirestoreService Flow Operations")
    print("=" * 60)
    
    service = MockFirestoreService()
    
    # Test 1: Create Flow
    print("\n1. Testing create_flow...")
    flow_id = service.create_flow("test-flow-1", {
        'flow_name': 'Test Flow',
        'document_count': 0
    })
    print(f"   ✅ Created flow: {flow_id}")
    
    # Test 2: Get Flow
    print("\n2. Testing get_flow...")
    flow = service.get_flow(flow_id)
    assert flow is not None, "Flow should exist"
    assert flow['flow_name'] == 'Test Flow', "Flow name should match"
    print(f"   ✅ Retrieved flow: {flow['flow_name']}")
    
    # Test 3: List Flows
    print("\n3. Testing list_flows...")
    flows, total = service.list_flows(page=1, page_size=10)
    assert total >= 1, "Should have at least 1 flow"
    print(f"   ✅ Listed {total} flow(s)")
    
    # Test 4: Update Flow
    print("\n4. Testing update_flow...")
    result = service.update_flow(flow_id, {'flow_name': 'Updated Flow Name'})
    assert result is True, "Update should succeed"
    updated_flow = service.get_flow(flow_id)
    assert updated_flow['flow_name'] == 'Updated Flow Name', "Flow name should be updated"
    print(f"   ✅ Updated flow name to: {updated_flow['flow_name']}")
    
    # Test 5: Create Document with Flow ID
    print("\n5. Testing create_document with flow_id...")
    doc_id = service.create_document("test-doc-1", {
        'filename': 'test.pdf',
        'flow_id': flow_id,
        'processing_status': 'pending'
    })
    print(f"   ✅ Created document: {doc_id}")
    
    # Test 6: Increment Flow Document Count
    print("\n6. Testing increment_flow_document_count...")
    result = service.increment_flow_document_count(flow_id, 1)
    assert result is True, "Increment should succeed"
    flow_after = service.get_flow(flow_id)
    assert flow_after['document_count'] == 1, "Document count should be 1"
    print(f"   ✅ Incremented count to: {flow_after['document_count']}")
    
    # Test 7: Get Documents by Flow ID
    print("\n7. Testing get_documents_by_flow_id...")
    docs, doc_total = service.get_documents_by_flow_id(flow_id, page=1, page_size=10)
    assert doc_total == 1, "Should have 1 document"
    assert docs[0]['document_id'] == doc_id, "Document ID should match"
    print(f"   ✅ Retrieved {doc_total} document(s) for flow")
    
    # Test 8: List Documents with Flow ID Filter
    print("\n8. Testing list_documents with flow_id filter...")
    docs_filtered, total_filtered = service.list_documents(page=1, page_size=10, filters={'flow_id': flow_id})
    assert total_filtered == 1, "Should have 1 document with flow_id filter"
    print(f"   ✅ Filtered documents: {total_filtered}")
    
    print("\n" + "=" * 60)
    print("✅ All MockFirestoreService flow operations working correctly!")
    print("=" * 60)

if __name__ == "__main__":
    try:
        test_mock_flow_operations()
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

